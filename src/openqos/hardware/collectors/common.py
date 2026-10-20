"""Helpers shared by collectors."""

from __future__ import annotations

from pathlib import Path

from openqos.hardware.context import CollectionContext

#: PCI class codes -> coarse device category. Only classes OpenQOS acts on are listed.
PCI_CLASS_NAMES: dict[str, str] = {
    "01": "storage",
    "02": "network",
    "03": "display",
    "04": "multimedia",
    "06": "bridge",
    "08": "system-peripheral",
    "0c": "serial-bus",
    "0d": "wireless",
}

PCI_SUBCLASS_NAMES: dict[str, str] = {
    "0106": "sata-controller",
    "0108": "nvme-controller",
    "0280": "wifi-controller",
    "0282": "mobile-broadband",
    "0300": "vga-compatible",
    "0301": "xga-compatible",
    "0302": "3d-controller",
    "0401": "audio-controller",
    "0403": "audio-controller",
    "0c03": "usb-controller",
    "0d11": "bluetooth-controller",
}


def pci_class_code(uevent: dict[str, str], raw_class: str | None) -> str | None:
    """Normalise the different ways sysfs exposes a PCI class code."""
    from_uevent = uevent.get("PCI_CLASS")
    if from_uevent:
        return from_uevent.lower().zfill(6)
    if raw_class:
        value = raw_class.lower()
        if value.startswith("0x"):
            value = value[2:]
        return value.zfill(6)
    return None


def pci_category(class_code: str | None) -> str | None:
    if not class_code or len(class_code) < 6:
        return None
    key = class_code[:4]
    if key in PCI_SUBCLASS_NAMES:
        return PCI_SUBCLASS_NAMES[key]
    return PCI_CLASS_NAMES.get(class_code[:2])


def driver_name(ctx: CollectionContext, device: Path, *, root: Path) -> str | None:
    """Resolve the bound driver name for a sysfs device directory."""
    try:
        relative = device.relative_to(root)
    except ValueError:
        return None
    link = ctx.fs.link_name(*relative.parts, "driver")
    if link:
        return link
    uevent = ctx.fs.key_values(*relative.parts, "uevent")
    return uevent.get("DRIVER") or None


def optional_text(ctx: CollectionContext, device: Path, *, root: Path, name: str) -> str | None:
    try:
        relative = device.relative_to(root)
    except ValueError:
        return None
    return ctx.fs.text(*relative.parts, name)


def device_id(prefix: str, name: str) -> str:
    """Build a stable, human readable identifier for a device record."""
    return f"{prefix}:{name}"
