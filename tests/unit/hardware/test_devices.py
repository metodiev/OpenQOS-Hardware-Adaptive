"""Tests for PCI, graphics, USB, storage, and network collection."""

from __future__ import annotations

from pathlib import Path

import pytest

from openqos.hardware.collectors.network import collect_network
from openqos.hardware.collectors.pci import collect_graphics, collect_pci
from openqos.hardware.collectors.storage import collect_storage
from openqos.hardware.collectors.usb import collect_usb
from openqos.hardware.context import CollectionContext


def _ctx(root: Path, *, privacy: bool = False) -> CollectionContext:
    return CollectionContext.create(root, privacy=privacy)


def test_pci_classification(intel_laptop_tree: Path) -> None:
    devices = collect_pci(_ctx(intel_laptop_tree))
    by_slot = {device["slot"]: device for device in devices}
    assert by_slot["0000:00:02.0"]["category"] == "vga-compatible"
    assert by_slot["0000:00:02.0"]["driver"] == "i915"
    assert by_slot["0000:00:14.3"]["category"] == "wifi-controller"
    assert by_slot["0000:00:1f.2"]["category"] == "sata-controller"
    assert by_slot["0000:00:1f.3"]["class_code"] == "040300"
    assert by_slot["0000:01:00.0"]["subsystem_vendor_id"] == "17aa"


def test_graphics_detects_hybrid_laptop(intel_laptop_tree: Path) -> None:
    ctx = _ctx(intel_laptop_tree)
    graphics = collect_graphics(ctx, collect_pci(ctx))
    assert graphics["adapter_count"] == 2
    assert graphics["hybrid_graphics"] is True
    assert graphics["primary_adapter"] == "i915"
    nvidia = next(adapter for adapter in graphics["adapters"] if adapter["driver"] == "nvidia")
    assert nvidia["memory_mib"] == 4096


def test_graphics_single_amd_adapter(amd_desktop_tree: Path) -> None:
    ctx = _ctx(amd_desktop_tree)
    graphics = collect_graphics(ctx, collect_pci(ctx))
    assert graphics["adapter_count"] == 1
    assert graphics["hybrid_graphics"] is False
    assert graphics["adapters"][0]["memory_mib"] == 2048


def test_usb_devices(intel_laptop_tree: Path) -> None:
    devices = collect_usb(_ctx(intel_laptop_tree))
    assert {device["bus_port"] for device in devices} == {"1-3", "1-5"}
    receiver = next(device for device in devices if device["bus_port"] == "1-3")
    assert receiver["vendor_id"] == "046d"
    assert receiver["product"] == "USB Receiver"
    camera = next(device for device in devices if device["bus_port"] == "1-5")
    assert camera["serial"] is None


@pytest.mark.linux_only
def test_usb_interface_binding(intel_laptop_tree: Path) -> None:
    devices = {device["bus_port"]: device for device in collect_usb(_ctx(intel_laptop_tree))}
    assert devices["1-3"]["interfaces"][0]["driver"] == "usbhid"
    assert devices["1-5"]["interfaces"][0]["driver"] == "uvcvideo"


def test_usb_privacy_removes_serial(intel_laptop_tree: Path) -> None:
    devices = collect_usb(_ctx(intel_laptop_tree, privacy=True))
    assert all(device["serial"] is None for device in devices)


def test_storage_device_and_partitions(intel_laptop_tree: Path) -> None:
    devices = collect_storage(_ctx(intel_laptop_tree))
    assert len(devices) == 1
    nvme = devices[0]
    assert nvme["name"] == "nvme0n1"
    assert nvme["transport"] == "nvme"
    assert nvme["rotational"] is False
    assert nvme["size_gib"] == round(1_000_204_800 * 512 / (1024**3), 2)
    assert [part["name"] for part in nvme["partitions"]] == [
        "nvme0n1p1",
        "nvme0n1p2",
        "nvme0n1p3",
    ]


def test_storage_hdd_is_rotational(amd_desktop_tree: Path) -> None:
    devices = {device["name"]: device for device in collect_storage(_ctx(amd_desktop_tree))}
    assert devices["sda"]["rotational"] is True
    assert devices["sda"]["transport"] == "sata"
    assert devices["nvme0n1"]["transport"] == "nvme"


def test_storage_privacy_removes_serial(intel_laptop_tree: Path) -> None:
    devices = collect_storage(_ctx(intel_laptop_tree, privacy=True))
    assert devices[0]["serial"] is None


def test_network_wireless_detection(intel_laptop_tree: Path) -> None:
    interfaces = {entry["name"]: entry for entry in collect_network(_ctx(intel_laptop_tree))}
    assert interfaces["wlan0"]["type"] == "wireless"
    assert interfaces["wlan0"]["driver"] == "iwlwifi"
    assert interfaces["wlan0"]["pci_slot"] == "0000:00:14.3"
    assert interfaces["enp0s31f6"]["type"] == "ethernet"
    assert interfaces["enp0s31f6"]["speed_mbps"] == 1000


def test_network_privacy_removes_mac(intel_laptop_tree: Path) -> None:
    interfaces = collect_network(_ctx(intel_laptop_tree, privacy=True))
    assert all(entry["mac_address"] is None for entry in interfaces)


def test_empty_tree_reports_unavailable(minimal_tree: Path) -> None:
    ctx = _ctx(minimal_tree)
    assert collect_pci(ctx) == []
    assert collect_storage(ctx) == []
    assert collect_network(ctx) == []
    assert collect_usb(ctx) == []
    collectors = {entry["collector"] for entry in ctx.unavailable}
    assert {"pci", "storage", "network", "usb"} <= collectors
