"""Overlay application and build execution."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from openqos import __version__
from openqos.errors import ImageBuildError
from openqos.imagebuilder.plan import BASE_IMAGE_PROFILE, BASE_KIWI_FILE, FEDORA_RELEASE

_KIWI_INCLUDE = '<include from="this://./components/openqos.xml"/>'


def apply_overlay(description_dir: Path, overlay_dir: Path, project_root: Path) -> list[str]:
    """Copy the OpenQOS overlay into a checked-out kiwi description directory.

    Returns the list of paths that were created or modified. Repeated calls are
    safe: the include line and the ``config.sh`` block are only added once.
    """
    if not description_dir.is_dir():
        raise ImageBuildError(f"description directory {description_dir} does not exist")
    changed: list[str] = []

    component_source = overlay_dir / "components" / "openqos.xml"
    component_target = description_dir / "components" / "openqos.xml"
    if not component_source.is_file():
        raise ImageBuildError(f"missing overlay component {component_source}")
    component_target.parent.mkdir(parents=True, exist_ok=True)
    _copy_normalised(component_source, component_target)
    changed.append(str(component_target))

    root_overlay = overlay_dir / "root"
    if root_overlay.is_dir():
        for source in root_overlay.rglob("*"):
            if not source.is_file():
                continue
            target = description_dir / "root" / source.relative_to(root_overlay)
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_normalised(source, target)
            changed.append(str(target))

    release_marker = description_dir / "root" / "etc" / "openqos-release"
    release_marker.parent.mkdir(parents=True, exist_ok=True)
    release_marker.write_bytes(
        (
            "OpenQOS live environment\n"
            f"base=Fedora Linux {FEDORA_RELEASE}\n"
            f"openqos={__version__}\n"
        ).encode()
    )
    changed.append(str(release_marker))

    # Anaconda and dnf resolve $releasever from /etc/system-release. The medium
    # ships a fixed release, so state it instead of letting them guess.
    dnf_releasever = description_dir / "root" / "etc" / "dnf" / "vars" / "releasever"
    dnf_releasever.parent.mkdir(parents=True, exist_ok=True)
    dnf_releasever.write_bytes(f"{FEDORA_RELEASE}\n".encode())
    changed.append(str(dnf_releasever))
    changed.extend(_enable_units(description_dir, ("openqos-scan.service",)))
    # Bind mounts and Windows hosts do not carry POSIX modes, so set them.
    _set_tree_modes(
        description_dir / "root", executable={"openqos", "openqos-summary-window"}
    )

    package_source = project_root / "src" / "openqos"
    package_target = description_dir / "root" / "opt" / "openqos" / "src" / "openqos"
    if not package_source.is_dir():
        raise ImageBuildError(f"missing source package {package_source}")
    if package_target.exists():
        shutil.rmtree(package_target)
    shutil.copytree(
        package_source,
        package_target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        copy_function=_copy_normalised,
    )
    _set_tree_modes(package_target)
    changed.append(str(package_target))

    kiwi_file = description_dir / BASE_KIWI_FILE
    if not kiwi_file.is_file():
        raise ImageBuildError(f"{kiwi_file} is missing from the description")
    content = kiwi_file.read_text(encoding="utf-8")
    if _KIWI_INCLUDE not in content:
        kiwi_file.write_bytes(_append_include(content).encode("utf-8"))
        changed.append(str(kiwi_file))
    return list(dict.fromkeys(changed))


def _copy_normalised(source: str | Path, target: str | Path) -> Path:
    """Copy a file into the image, forcing LF line endings for text files.

    A Windows checkout stores text files with CRLF. A shell script with a CRLF
    shebang is not executable on Linux, so the image must not inherit the host
    line endings.
    """
    source_path = Path(source)
    target_path = Path(target)
    data = source_path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        target_path.write_bytes(data)
        return target_path
    target_path.write_bytes(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))
    return target_path


def _enable_units(description_dir: Path, units: tuple[str, ...]) -> list[str]:
    """Enable units by creating relative symlinks in multi-user.target.wants.

    The overlay tree cannot carry symlinks portably (a Windows checkout stores
    them as plain files), so they are created here on the Linux build host.
    """
    changed: list[str] = []
    wants = description_dir / "root" / "etc" / "systemd" / "system" / "multi-user.target.wants"
    wants.mkdir(parents=True, exist_ok=True)
    for unit in units:
        link = wants / unit
        target = f"../../../../usr/lib/systemd/system/{unit}"
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(target)
            changed.append(str(link))
        except OSError:  # pragma: no cover - Windows without symlink privileges
            continue
    return changed


def _set_tree_modes(root: Path, *, executable: frozenset[str] | set[str] = frozenset()) -> None:
    """Give copied overlay files deterministic POSIX permissions."""
    for path in [root, *sorted(root.rglob("*"))]:
        try:
            if path.is_dir() or path.name in executable:
                path.chmod(0o755)
            else:
                path.chmod(0o644)
        except OSError:  # pragma: no cover - permissions are best effort
            continue


def _append_include(content: str) -> str:
    marker = '<packages type="bootstrap">'
    if marker not in content:
        return content.rstrip("\n") + "\n" + _KIWI_INCLUDE + "\n"
    head, _, tail = content.partition(marker)
    return f"{head}{_KIWI_INCLUDE}\n\t{marker}{tail}"


def run_build(
    description_dir: Path,
    output_dir: Path,
    *,
    log_path: Path | None = None,
    runner: Any = None,
) -> Path:
    """Run ``kiwi-build`` for the pinned profile and return the produced ISO path."""
    runner = runner or subprocess.run
    command = [
        "./kiwi-build",
        f"--kiwi-description-dir={description_dir}",
        f"--kiwi-file={BASE_KIWI_FILE}",
        "--image-type=iso",
        f"--image-profile={BASE_IMAGE_PROFILE}",
        f"--output-dir={output_dir}",
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    completed = runner(
        command,
        cwd=str(description_dir),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(completed.stdout or "", encoding="utf-8")
    if completed.returncode != 0:
        raise ImageBuildError(
            f"kiwi-build failed with exit code {completed.returncode}; "
            f"see {log_path or 'the build output'}"
        )

    images = _find_images(output_dir)
    if not images:
        raise ImageBuildError(f"kiwi-build reported success but no ISO was found in {output_dir}")
    return images[0]


def _find_images(output_dir: Path) -> list[Path]:
    """Locate ISOs in the output directory or the kiwi target directory.

    ``kiwi-build`` passes ``--target-dir "<output-dir>-build"`` to ``kiwi-ng``,
    so the finished image is written next to the requested output directory.
    """
    candidates: list[Path] = []
    for directory in (output_dir, output_dir.parent / f"{output_dir.name}-build"):
        if directory.is_dir():
            candidates.extend(directory.glob("*.iso"))
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)
