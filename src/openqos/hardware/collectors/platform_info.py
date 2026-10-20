"""Operating system, kernel, firmware, and virtualization detection."""

from __future__ import annotations

import platform
from typing import Any

from openqos.hardware.context import CollectionContext

#: efivar files start with a 4 byte attribute mask, the value byte follows.
_SECURE_BOOT_VAR = "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
_SETUP_MODE_VAR = "SetupMode-8be4df61-93ca-11d2-aa0d-00e098032b8c"

_VIRTUAL_VENDORS = {
    "kvm",
    "qemu",
    "vmware",
    "virtualbox",
    "innotek gmbh",
    "microsoft corporation",
    "xen",
    "bochs",
    "parallels software international inc.",
    "amazon ec2",
    "google compute engine",
    "digitalocean",
    "openstack",
}


def collect_platform(ctx: CollectionContext) -> dict[str, Any]:
    """Collect host identity and boot environment information."""
    os_release = ctx.fs.key_values("etc", "os-release")
    if not os_release:
        ctx.unavailable_reason("platform.os", "/etc/os-release is not readable")

    kernel = _collect_kernel(ctx)
    firmware = _collect_firmware(ctx)
    dmi_vendor = ctx.fs.text("sys", "class", "dmi", "id", "sys_vendor")
    dmi_product = ctx.fs.text("sys", "class", "dmi", "id", "product_name")
    virtualization = _collect_virtualization(ctx, dmi_vendor, dmi_product)

    return {
        "hostname": ctx.redact(platform.node() or None),
        "os": {
            "id": os_release.get("ID"),
            "version_id": os_release.get("VERSION_ID"),
            "pretty_name": os_release.get("PRETTY_NAME"),
            "variant": os_release.get("VARIANT") or os_release.get("VARIANT_ID"),
            "build_id": os_release.get("BUILD_ID"),
            "id_like": [item for item in os_release.get("ID_LIKE", "").split() if item],
        }
        if os_release
        else None,
        "kernel": kernel,
        "firmware": firmware,
        "virtualization": virtualization,
    }


def _collect_kernel(ctx: CollectionContext) -> dict[str, Any] | None:
    release = ctx.fs.text("proc", "sys", "kernel", "osrelease")
    if release is None:
        ctx.unavailable_reason("platform.kernel", "/proc/sys/kernel/osrelease is not readable")
        return None
    return {
        "release": release,
        "version": ctx.fs.text("proc", "version"),
        "architecture": platform.machine() or None,
        "cmdline": ctx.redact(ctx.fs.text("proc", "cmdline")),
    }


def _read_efi_flag(ctx: CollectionContext, name: str) -> str:
    raw = ctx.fs.raw_bytes("sys", "firmware", "efi", "efivars", name)
    if raw is None:
        return "unknown"
    if len(raw) < 5:
        ctx.warn(
            "firmware.efivar-short",
            f"EFI variable {name} is shorter than expected",
            "platform.firmware",
        )
        return "unknown"
    return "enabled" if raw[4] else "disabled"


def _collect_firmware(ctx: CollectionContext) -> dict[str, Any]:
    is_efi = ctx.fs.is_dir("sys", "firmware", "efi")
    boot_mode = "uefi" if is_efi else "bios"
    if not ctx.fs.is_dir("sys", "firmware"):
        boot_mode = "unknown"
        ctx.unavailable_reason("platform.firmware", "/sys/firmware is not available")
    return {
        "boot_mode": boot_mode,
        "secure_boot": _read_efi_flag(ctx, _SECURE_BOOT_VAR) if is_efi else "unknown",
        "setup_mode": _read_efi_flag(ctx, _SETUP_MODE_VAR) if is_efi else "unknown",
    }


def _collect_virtualization(
    ctx: CollectionContext, dmi_vendor: str | None, dmi_product: str | None
) -> dict[str, Any]:
    cpuinfo = ctx.fs.text("proc", "cpuinfo") or ""
    hypervisor_flag = "hypervisor" in cpuinfo
    xenhyp = ctx.fs.text("sys", "hypervisor", "type")
    vendor_lower = (dmi_vendor or "").lower()

    hypervisor: str | None = None
    if xenhyp:
        hypervisor = xenhyp
    elif vendor_lower:
        for known in sorted(_VIRTUAL_VENDORS):
            if known in vendor_lower:
                hypervisor = known
                break

    return {
        "is_virtual_machine": bool(hypervisor or hypervisor_flag),
        "hypervisor": hypervisor,
        "vendor": ctx.redact(dmi_vendor),
        "product": ctx.redact(dmi_product),
    }
