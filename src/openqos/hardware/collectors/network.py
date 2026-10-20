"""Network interface detection."""

from __future__ import annotations

from typing import Any

from openqos.hardware.context import CollectionContext

_NET_ROOT = ("sys", "class", "net")
_VIRTUAL_PREFIXES = ("lo", "veth", "virbr", "docker", "br-", "vnet", "tun", "tap", "wg")
_ARPHRD_ETHER = "1"
_ARPHRD_LOOPBACK = "772"


def collect_network(ctx: CollectionContext) -> list[dict[str, Any]]:
    interfaces: list[dict[str, Any]] = []
    for entry in ctx.fs.subdirectories(*_NET_ROOT):
        name = entry.name
        if name == "lo":
            continue
        record = {
            "name": name,
            "type": _interface_type(ctx, entry),
            "mac_address": ctx.redact(ctx.fs.text(*entry.parts, "address")),
            "state": ctx.fs.text(*entry.parts, "operstate"),
            "speed_mbps": ctx.fs.integer(*entry.parts, "speed") or None,
            "driver": ctx.fs.link_name(*entry.parts, "device", "driver")
            or ctx.fs.key_values(*entry.parts, "device", "uevent").get("DRIVER"),
            "firmware_version": ctx.fs.text(*entry.parts, "device", "firmware_version"),
            "pci_slot": _pci_slot(ctx, entry),
            "virtual": name.startswith(_VIRTUAL_PREFIXES),
        }
        interfaces.append(record)

    if not interfaces:
        ctx.unavailable_reason("network", "no network interfaces were found under /sys/class/net")
    return interfaces


def _interface_type(ctx: CollectionContext, entry: Any) -> str:
    if ctx.fs.is_dir(*entry.parts, "wireless") or ctx.fs.is_dir(*entry.parts, "phy80211"):
        return "wireless"
    arphrd = ctx.fs.text(*entry.parts, "type")
    if arphrd == _ARPHRD_LOOPBACK:
        return "loopback"
    if arphrd == _ARPHRD_ETHER:
        return "ethernet"
    return "other"


def _pci_slot(ctx: CollectionContext, entry: Any) -> str | None:
    uevent = ctx.fs.key_values(*entry.parts, "device", "uevent")
    return uevent.get("PCI_SLOT_NAME")
