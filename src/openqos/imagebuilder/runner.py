"""Overlay application and build execution."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from openqos.errors import ImageBuildError
from openqos.imagebuilder.plan import BASE_IMAGE_PROFILE, BASE_KIWI_FILE

_KIWI_INCLUDE = '<include from="this://./components/openqos.xml"/>'
_OVERLAY_MARKER = "# --- OpenQOS overlay (managed by openqos image build) ---"


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
    shutil.copy2(component_source, component_target)
    changed.append(str(component_target))

    root_overlay = overlay_dir / "root"
    if root_overlay.is_dir():
        for source in root_overlay.rglob("*"):
            if not source.is_file():
                continue
            target = description_dir / "root" / source.relative_to(root_overlay)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            changed.append(str(target))

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
    )
    changed.append(str(package_target))

    kiwi_file = description_dir / BASE_KIWI_FILE
    if not kiwi_file.is_file():
        raise ImageBuildError(f"{kiwi_file} is missing from the description")
    content = kiwi_file.read_text(encoding="utf-8")
    if _KIWI_INCLUDE not in content:
        kiwi_file.write_text(_append_include(content), encoding="utf-8")
        changed.append(str(kiwi_file))

    config_script = description_dir / "config.sh"
    append_source = overlay_dir / "config.sh.append"
    if append_source.is_file():
        addition = append_source.read_text(encoding="utf-8")
        existing = config_script.read_text(encoding="utf-8") if config_script.is_file() else ""
        if _OVERLAY_MARKER not in existing:
            config_script.write_text(existing.rstrip("\n") + "\n\n" + addition, encoding="utf-8")
            changed.append(str(config_script))
    return changed


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

    images = sorted(output_dir.glob("*.iso"))
    if not images:
        raise ImageBuildError(f"kiwi-build reported success but no ISO was found in {output_dir}")
    return images[0]
