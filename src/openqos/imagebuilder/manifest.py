"""Artifact verification and manifest generation."""

from __future__ import annotations

import datetime as _dt
import hashlib
from pathlib import Path
from typing import Any

from openqos.errors import ImageBuildError

_ISO9660_MAGIC = b"CD001"
_ISO9660_OFFSETS = (0x8001, 0x8801, 0x9001)


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_iso(path: Path) -> dict[str, Any]:
    """Check that ``path`` looks like a bootable ISO 9660 image."""
    if not path.is_file():
        raise ImageBuildError(f"expected ISO at {path}, but it does not exist")
    size = path.stat().st_size
    if size < 1024 * 1024:
        raise ImageBuildError(f"{path} is only {size} bytes, far too small for a live ISO")

    with path.open("rb") as handle:
        head = handle.read(0x9000)
    if not any(
        head[offset : offset + len(_ISO9660_MAGIC)] == _ISO9660_MAGIC
        for offset in _ISO9660_OFFSETS
    ):
        raise ImageBuildError(f"{path} does not contain an ISO 9660 volume descriptor")

    return {
        "path": str(path),
        "size_bytes": size,
        "size_mib": round(size / (1024 * 1024), 1),
        "sha256": sha256_file(path),
    }


def build_manifest(
    artifact: dict[str, Any],
    *,
    plan: dict[str, Any],
    package_versions: dict[str, str] | None = None,
    source_revision: str | None = None,
) -> dict[str, Any]:
    """Assemble a build manifest describing exactly what produced the ISO."""
    return {
        "manifest_version": "1.0.0",
        "generated_at": _dt.datetime.now(tz=_dt.UTC).replace(microsecond=0).isoformat(),
        "artifact": artifact,
        "profile": plan["profile"],
        "environment": plan["environment"],
        "package_versions": dict(sorted((package_versions or {}).items())),
        "source_revision": source_revision,
        "checksum_algorithm": "sha256",
    }


def write_manifest(manifest: dict[str, Any], path: Path) -> Path:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path
