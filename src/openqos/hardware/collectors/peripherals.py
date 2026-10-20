"""Audio, camera, input, and Bluetooth device detection."""

from __future__ import annotations

from typing import Any

from openqos.hardware.context import CollectionContext


def collect_audio(ctx: CollectionContext) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    for card in ctx.fs.subdirectories("proc", "asound"):
        card_id = ctx.fs.text(*card.parts, "id")
        if card_id is None:
            continue
        cards.append(
            {
                "name": card.name,
                "id": card_id,
                "driver": _module_of(ctx, card.name),
            }
        )
    if not cards:
        ctx.unavailable_reason("audio", "/proc/asound exposes no sound cards")
    return {"cards": cards}


def _module_of(ctx: CollectionContext, card_name: str) -> str | None:
    """Resolve the kernel module bound to a sound card via its device link."""
    return ctx.fs.link_name("sys", "class", "sound", card_name, "device", "driver")


def collect_cameras(ctx: CollectionContext) -> list[dict[str, Any]]:
    cameras: list[dict[str, Any]] = []
    for entry in ctx.fs.subdirectories("sys", "class", "video4linux"):
        cameras.append(
            {
                "id": entry.name,
                "name": ctx.fs.text(*entry.parts, "name"),
                "driver": ctx.fs.link_name(*entry.parts, "device", "driver"),
            }
        )
    if not cameras:
        ctx.unavailable_reason("cameras", "no video4linux devices were detected")
    return cameras


def collect_input_devices(ctx: CollectionContext) -> list[dict[str, Any]]:
    raw = ctx.fs.text("proc", "bus", "input", "devices")
    if not raw:
        ctx.unavailable_reason("input", "/proc/bus/input/devices is not readable")
        return []

    devices: list[dict[str, Any]] = []
    current: dict[str, str] = {}

    def flush() -> None:
        if current.get("Name"):
            devices.append(
                {
                    "name": current["Name"],
                    "bus": current.get("Bus"),
                    "vendor_id": current.get("Vendor"),
                    "product_id": current.get("Product"),
                    "handlers": current.get("Handlers", "").split(),
                }
            )

    for line in [*raw.splitlines(), ""]:
        if not line.strip():
            flush()
            current = {}
            continue
        prefix, _, rest = line.partition(":")
        rest = rest.strip()
        if prefix == "N":
            _, _, name = rest.partition("=")
            current["Name"] = (name or rest).strip().strip('"')
        elif prefix in {"I", "P"}:
            for token in rest.split():
                key, separator, value = token.partition("=")
                if separator:
                    current[key] = value
        elif prefix == "H":
            key, separator, value = rest.partition("=")
            if separator:
                current[key.strip()] = value.strip()
    return devices


def collect_bluetooth(ctx: CollectionContext) -> list[dict[str, Any]]:
    adapters: list[dict[str, Any]] = []
    for entry in ctx.fs.subdirectories("sys", "class", "bluetooth"):
        adapters.append(
            {
                "id": entry.name,
                "address": ctx.redact(ctx.fs.text(*entry.parts, "address")),
                "type": ctx.fs.text(*entry.parts, "type"),
                "bus": ctx.fs.text(*entry.parts, "bus"),
            }
        )
    if not adapters:
        ctx.unavailable_reason("bluetooth", "no Bluetooth adapters were detected")
    return adapters
