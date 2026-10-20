"""Automated installer planning and execution."""

from __future__ import annotations

from openqos.installer.disks import MINIMUM_DISK_GIB, DiskCandidate, enumerate_disks
from openqos.installer.plan import (
    INSTALL_PLAN_SCHEMA_VERSION,
    build_install_plan,
    render_kickstart,
    validate_install_plan,
)
from openqos.installer.runner import confirm_target, run_installer, write_kickstart

__all__ = [
    "INSTALL_PLAN_SCHEMA_VERSION",
    "MINIMUM_DISK_GIB",
    "DiskCandidate",
    "build_install_plan",
    "confirm_target",
    "enumerate_disks",
    "render_kickstart",
    "run_installer",
    "validate_install_plan",
    "write_kickstart",
]
