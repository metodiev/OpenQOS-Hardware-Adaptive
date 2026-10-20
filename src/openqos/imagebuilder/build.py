"""End-to-end image build orchestration."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from openqos.errors import ImageBuildError
from openqos.imagebuilder.manifest import build_manifest, verify_iso, write_manifest
from openqos.imagebuilder.plan import (
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
    """Return the OpenQOS git revision, or ``None`` outside a git checkout."""
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
    return (completed.stdout or "").strip() or None


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
        source_revision=source_revision(project_root, runner=runner),
    )
    manifest["overlay_files"] = [_relative_or_absolute(item, project_root) for item in changed]

    releases_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = releases_directory / f"{iso_path.stem}.manifest.json"
    write_manifest(manifest, manifest_path)

    checksum_path = releases_directory / f"{iso_path.name}.sha256"
    checksum_path.write_text(f"{artifact['sha256']}  {iso_path.name}\n", encoding="utf-8")

    released_iso = releases_directory / iso_path.name
    if released_iso.resolve() != iso_path.resolve():
        shutil.copy2(iso_path, released_iso)

    manifest["manifest_path"] = str(manifest_path)
    manifest["checksum_path"] = str(checksum_path)
    manifest["released_iso"] = str(released_iso)
    return manifest
