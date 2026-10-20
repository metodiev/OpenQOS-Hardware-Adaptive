"""Host readiness checks for an ISO build."""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openqos.imagebuilder.plan import FEDORA_RELEASE, HOST_PACKAGES

_MINIMUM_FREE_BYTES = 20 * 1024**3


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "required": self.required,
        }


def run_preflight(
    *,
    work_directory: Path | None = None,
    release_file: Path = Path("/etc/os-release"),
    system: str | None = None,
) -> list[Check]:
    """Collect host checks. Never modifies the host."""
    checks: list[Check] = []
    system = system or platform.system()

    checks.append(
        Check("linux-host", system == "Linux", f"platform is {system}", required=True)
    )

    os_release = _parse_os_release(release_file)
    distro_id = os_release.get("ID", "")
    checks.append(
        Check(
            "fedora-host",
            distro_id == "fedora",
            f"distribution id is {distro_id or 'unknown'}",
            required=True,
        )
    )
    version = os_release.get("VERSION_ID", "")
    checks.append(
        Check(
            "fedora-release",
            version == FEDORA_RELEASE,
            f"release is {version or 'unknown'}, expected {FEDORA_RELEASE}",
            required=False,
        )
    )

    for tool in HOST_PACKAGES:
        binary = "kiwi-ng" if tool == "kiwi-cli" else tool
        found = shutil.which(binary)
        checks.append(
            Check(f"tool:{tool}", found is not None, found or f"{binary} not found on PATH")
        )

    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    checks.append(
        Check("root-privileges", is_root, "image creation needs root for loop devices and chroot")
    )

    kvm_ok = Path("/dev/kvm").exists()
    checks.append(
        Check(
            "kvm",
            kvm_ok,
            "/dev/kvm is available"
            if kvm_ok
            else "/dev/kvm is missing (only needed for boot tests)",
            required=False,
        )
    )

    if work_directory is not None:
        free = _free_bytes(work_directory)
        checks.append(
            Check(
                "disk-space",
                free is not None and free >= _MINIMUM_FREE_BYTES,
                f"{_gib(free)} GiB free at {work_directory}, need at least "
                f"{_gib(_MINIMUM_FREE_BYTES)} GiB",
            )
        )
    return checks


def required_failures(checks: list[Check]) -> list[Check]:
    return [check for check in checks if check.required and not check.ok]


def _parse_os_release(path: Path) -> dict[str, str]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in content.splitlines():
        key, separator, value = line.partition("=")
        if separator and not line.lstrip().startswith("#"):
            values[key.strip()] = value.strip().strip('"')
    return values


def _free_bytes(path: Path) -> int | None:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def _gib(value: int | None) -> str:
    return "unknown" if value is None else f"{value / (1024**3):.1f}"
