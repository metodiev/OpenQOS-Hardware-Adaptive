"""End-to-end image build orchestration."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from openqos.errors import ImageBuildError
from openqos.imagebuilder.manifest import build_manifest, verify_iso, write_manifest
from openqos.imagebuilder.plan import (
    FEDORA_RELEASE,
    HOST_REQUIREMENTS,
    KIWI_DESCRIPTIONS_BRANCH,
    KIWI_DESCRIPTIONS_COMMIT,
    KIWI_DESCRIPTIONS_REPOSITORY,
)
from openqos.imagebuilder.runner import apply_overlay, run_build


def clone_descriptions(destination: Path, *, runner: Any = None) -> Path:
    """Clone and pin the Fedora KIWI description used for the build."""
    runner = runner or subprocess.run
    if destination.is_dir():
        completed = runner(
            ["git", "-C", str(destination), "fetch", "--all", "--tags"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.returncode != 0:
            raise ImageBuildError(
                f"cannot refresh {destination}: {completed.stdout or completed.returncode}"
            )
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        completed = runner(
            [
                "git",
                "clone",
                "--branch",
                KIWI_DESCRIPTIONS_BRANCH,
                KIWI_DESCRIPTIONS_REPOSITORY,
                str(destination),
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.returncode != 0:
            raise ImageBuildError(
                f"cannot clone {KIWI_DESCRIPTIONS_REPOSITORY}: "
                f"{completed.stdout or completed.returncode}"
            )

    checkout = runner(
        ["git", "-C", str(destination), "checkout", "--detach", KIWI_DESCRIPTIONS_COMMIT],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if checkout.returncode != 0:
        raise ImageBuildError(
            f"cannot check out {KIWI_DESCRIPTIONS_COMMIT}: "
            f"{checkout.stdout or checkout.returncode}"
        )
    return destination


def _relative_or_absolute(item: str, project_root: Path) -> str:
    path = Path(item).resolve()
    try:
        return str(path.relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def source_revision(project_root: Path, *, runner: Any = None) -> str | None:
    """Return the OpenQOS git revision, or ``None`` outside a git checkout.

    A ``-dirty`` suffix marks a build from a tree with uncommitted changes, so a
    release manifest can never silently claim a clean revision.
    """
    runner = runner or subprocess.run
    completed = runner(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        return None
    revision = (completed.stdout or "").strip()
    if not revision:
        return None

    status = runner(
        ["git", "-C", str(project_root), "status", "--porcelain"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if status.returncode == 0 and (status.stdout or "").strip():
        return f"{revision}-dirty"
    return revision


def installed_package_versions(*, runner: Any = None) -> dict[str, str]:
    """Return the installed versions of the required build packages."""
    runner = runner or subprocess.run
    packages = [requirement.name for requirement in HOST_REQUIREMENTS if requirement.kind == "rpm"]
    completed = runner(
        ["rpm", "-q", "--qf", "%{NAME} %{VERSION}-%{RELEASE}\n", *packages],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        return {}
    versions: dict[str, str] = {}
    for line in (completed.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in packages:
            versions[parts[0]] = parts[1]
    return versions


def build_image(
    plan: dict[str, Any],
    *,
    project_root: Path,
    releases_directory: Path,
    runner: Any = None,
) -> dict[str, Any]:
    """Build, verify, and document the ISO described by ``plan``."""
    runner = runner or subprocess.run
    environment = plan["environment"]
    description_dir = Path(environment["description_directory"])
    output_dir = Path(environment["output_directory"])
    work_dir = Path(environment["work_directory"])

    clone_descriptions(description_dir, runner=runner)
    changed = apply_overlay(description_dir, project_root / "image" / "overlay", project_root)

    iso_path = run_build(
        description_dir,
        output_dir,
        log_path=work_dir / "kiwi-build.log",
        runner=runner,
    )
    artifact = verify_iso(iso_path)
    manifest = build_manifest(
        artifact,
        plan=plan,
        package_versions=installed_package_versions(runner=runner),
        source_revision=source_revision(project_root, runner=runner),
    )
    manifest["overlay_files"] = [_relative_or_absolute(item, project_root) for item in changed]

    releases_directory.mkdir(parents=True, exist_ok=True)
    release_name = f"openqos-{plan['profile']}-{FEDORA_RELEASE}.iso"
    manifest_path = releases_directory / f"{Path(release_name).stem}.manifest.json"

    checksum_path = releases_directory / f"{release_name}.sha256"
    checksum_path.write_text(f"{artifact['sha256']}  {release_name}\n", encoding="utf-8")

    released_iso = releases_directory / release_name
    if released_iso.resolve() != iso_path.resolve():
        shutil.copy2(iso_path, released_iso)

    manifest["released_iso"] = str(released_iso)
    manifest["manifest_path"] = str(manifest_path)
    manifest["checksum_path"] = str(checksum_path)
    write_manifest(manifest, manifest_path)
    return manifest
