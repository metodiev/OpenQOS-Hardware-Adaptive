"""USB device enumeration from sysfs."""

from __future__ import annotations

from typing import Any

from openqos.hardware.context import CollectionContext

_USB_ROOT = ("sys", "bus", "usb", "devices")


def collect_usb(ctx: CollectionContext) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for device_dir in ctx.fs.subdirectories(*_USB_ROOT):
        name = device_dir.name
        # Interface entries (``1-2:1.0``) describe a function of a device.
        if ":" in name:
            continue
        uevent = ctx.fs.key_values(*device_dir.parts, "uevent")
        product_id = uevent.get("PRODUCT", "")
        parts = product_id.split("/") if product_id else []
        vendor_id = parts[0] if parts else None
        device_id = parts[1] if len(parts) > 1 else None
        record: dict[str, Any] = {
            "id": f"usb:{name}",
            "bus_port": name,
            "vendor_id": vendor_id,
            "device_id": device_id,
            "manufacturer": ctx.redact(ctx.fs.text(*device_dir.parts, "manufacturer")),
            "product": ctx.fs.text(*device_dir.parts, "product"),
            "serial": ctx.redact(ctx.fs.text(*device_dir.parts, "serial")),
            "driver": ctx.fs.link_name(*device_dir.parts, "driver") or uevent.get("DRIVER"),
            "interfaces": _interfaces(ctx, name),
        }
        if record["vendor_id"] is None:
            ctx.warn(
                "usb.unidentified",
                f"USB device {name} exposes no PRODUCT identifier",
                "usb",
            )
        devices.append(record)
    if not devices:
        ctx.unavailable_reason("usb", "no USB devices were found under /sys/bus/usb/devices")
    return devices


def _interfaces(ctx: CollectionContext, parent: str) -> list[dict[str, Any]]:
    interfaces: list[dict[str, Any]] = []
    for entry in ctx.fs.subdirectories(*_USB_ROOT):
        if not entry.name.startswith(f"{parent}:"):
            continue
        uevent = ctx.fs.key_values(*entry.parts, "uevent")
        interfaces.append(
            {
                "id": entry.name,
                "class_code": uevent.get("INTERFACE"),
                "driver": ctx.fs.link_name(*entry.parts, "driver") or uevent.get("DRIVER"),
            }
        )
    return interfaces
