"""End-to-end tests for the hardware inventory document."""

from __future__ import annotations

import json
from pathlib import Path

from openqos import HARDWARE_SCHEMA_VERSION
from openqos.hardware.scanner import scan
from openqos.hardware.validate import load_document, validate_document

_SAMPLE = Path(__file__).resolve().parents[3] / "docs" / "samples" / "hardware-profile.json"


def _without_timestamp(document: dict) -> dict:
    stripped = dict(document)
    stripped.pop("generated_at", None)
    return stripped


def test_scan_intel_laptop_is_schema_valid(intel_laptop_tree: Path) -> None:
    document = scan(intel_laptop_tree)
    assert document["schema_version"] == HARDWARE_SCHEMA_VERSION
    assert document["privacy_mode"] is False
    assert validate_document(document) == []


def test_scan_is_json_serialisable(intel_laptop_tree: Path) -> None:
    document = scan(intel_laptop_tree)
    payload = json.dumps(document)
    assert json.loads(payload)["host"]["os"]["id"] == "fedora"


def test_scan_is_deterministic_except_timestamp(intel_laptop_tree: Path) -> None:
    first = scan(intel_laptop_tree)
    second = scan(intel_laptop_tree)
    assert _without_timestamp(first) == _without_timestamp(second)


def test_scan_privacy_mode_removes_identifiers(intel_laptop_tree: Path) -> None:
    document = scan(intel_laptop_tree, privacy=True)
    assert document["privacy_mode"] is True
    assert document["host"]["hostname"] is None
    assert document["host"]["virtualization"]["vendor"] is None
    assert document["storage"][0]["serial"] is None
    assert all(interface["mac_address"] is None for interface in document["network"])
    assert all(device["serial"] is None for device in document["usb_devices"])
    assert document["host"]["kernel"]["cmdline"] is None
    assert validate_document(document) == []


def test_scan_amd_desktop(amd_desktop_tree: Path) -> None:
    document = scan(amd_desktop_tree)
    assert document["cpu"]["vendors"] == ["AuthenticAMD"]
    assert document["graphics"]["adapter_count"] == 1
    assert document["power"]["batteries"] == []
    assert {device["transport"] for device in document["storage"]} == {"nvme", "sata"}
    assert validate_document(document) == []


def test_scan_minimal_host_does_not_fail(minimal_tree: Path) -> None:
    document = scan(minimal_tree)
    assert document["cpu"] is None
    assert document["graphics"]["adapter_count"] == 0
    assert document["storage"] == []
    assert document["memory"]["total_kib"] == 2_048_000
    assert document["unavailable"]
    assert validate_document(document) == []


def test_committed_sample_matches_schema() -> None:
    assert _SAMPLE.is_file(), "docs/samples/hardware-profile.json is missing"
    document = load_document(_SAMPLE)
    assert validate_document(document) == []


def test_committed_sample_has_no_private_identifiers() -> None:
    document = load_document(_SAMPLE)
    assert document["privacy_mode"] is True
    assert document["host"]["hostname"] is None
    assert all(device.get("serial") is None for device in document["usb_devices"])
    assert all(device.get("serial") is None for device in document["storage"])
    assert all(interface.get("mac_address") is None for interface in document["network"])


def test_device_strings_are_never_interpreted(tmp_path: Path) -> None:
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc" / "meminfo").write_text("MemTotal: 1024 kB\n", encoding="utf-8")
    usb = tmp_path / "sys" / "bus" / "usb" / "devices" / "9-9"
    usb.mkdir(parents=True)
    (usb / "uevent").write_text("PRODUCT=dead/beef/100\nDRIVER=usb\n", encoding="utf-8")
    (usb / "product").write_text("; rm -rf / #`id`$(whoami)\n", encoding="utf-8")

    document = scan(tmp_path)
    product = document["usb_devices"][0]["product"]
    assert product == "; rm -rf / #`id`$(whoami)"
    assert validate_document(document) == []
