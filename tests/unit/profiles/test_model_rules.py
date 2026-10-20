"""Tests for profile normalisation and rule matching."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openqos.errors import ProfileError
from openqos.hardware.scanner import scan
from openqos.optimizer.validate import validate_profile_document
from openqos.profiles.model import build_profile
from openqos.profiles.rules import (
    default_ruleset_path,
    load_ruleset,
    match_profile,
    validate_ruleset,
)


def _profile(root: Path) -> dict:
    profile = build_profile(scan(root))
    assert validate_profile_document(profile) == []
    return profile


def test_intel_laptop_profile(intel_laptop_tree: Path) -> None:
    profile = _profile(intel_laptop_tree)
    assert profile["machine"]["form_factor"] == "laptop"
    assert profile["machine"]["is_virtual_machine"] is False
    assert profile["machine"]["firmware"] == {"boot_mode": "uefi", "secure_boot": "enabled"}
    assert profile["cpu"]["vendor"] == "intel"
    assert profile["cpu"]["logical_cpus"] == 8
    assert profile["cpu"]["features"]["avx512f"] is True
    assert profile["memory"] == {
        "total_mib": 15360,
        "tier": "standard",
        "swap_total_mib": 8192,
        "has_swap": True,
    }
    assert profile["graphics"]["hybrid"] is True
    assert profile["graphics"]["requires_third_party_driver"] is True
    assert profile["storage"]["primary"] == "ssd"
    assert profile["storage"]["has_nvme"] is True
    assert profile["network"]["wireless"] is True
    assert profile["power"]["governor"] == "powersave"
    assert profile["power"]["platform_profile_supported"] is True
    assert profile["audio"]["card_count"] == 1
    assert "memory.modules" in profile["unavailable"]


def test_amd_desktop_profile(amd_desktop_tree: Path) -> None:
    profile = _profile(amd_desktop_tree)
    assert profile["machine"]["form_factor"] == "desktop"
    assert profile["machine"]["firmware"]["boot_mode"] == "bios"
    assert profile["cpu"]["vendor"] == "amd"
    assert profile["graphics"]["hybrid"] is False
    assert profile["graphics"]["primary_driver"] == "amdgpu"
    assert profile["storage"]["primary"] == "ssd"
    assert {device["transport"] for device in profile["storage"]["devices"]} == {
        "nvme",
        "sata",
    }
    assert profile["power"]["platform_profile_supported"] is False
    assert profile["cpu"]["features"]["virt_host"] is True


def test_minimal_profile_is_honest(minimal_tree: Path) -> None:
    profile = _profile(minimal_tree)
    assert profile["machine"]["form_factor"] == "unknown"
    assert profile["cpu"]["vendor"] == "unknown"
    assert profile["memory"]["total_mib"] == 2000
    assert profile["memory"]["tier"] == "low"
    assert profile["storage"]["primary"] == "unknown"
    assert profile["graphics"]["adapter_count"] == 0
    assert profile["unavailable"]


def test_build_profile_rejects_unknown_inventory_version(minimal_tree: Path) -> None:
    inventory = scan(minimal_tree)
    inventory["schema_version"] = "0.9.0"
    with pytest.raises(ProfileError):
        build_profile(inventory)


def test_default_ruleset_is_valid() -> None:
    ruleset = load_ruleset()
    assert ruleset.revision
    assert any(rule.fallback for rule in ruleset.rules)
    assert default_ruleset_path().is_file()


def test_hybrid_laptop_selects_hybrid_profile(intel_laptop_tree: Path) -> None:
    matched = match_profile(_profile(intel_laptop_tree), load_ruleset())
    assert matched["profile_id"] == "hybrid-graphics-laptop"
    assert matched["fallback"] is False
    assert matched["priority"] == 80
    assert len(matched["matched_conditions"]) == 2


def test_amd_desktop_selects_amd_profile(amd_desktop_tree: Path) -> None:
    matched = match_profile(_profile(amd_desktop_tree), load_ruleset())
    assert matched["profile_id"] == "amd-desktop"
    assert "amd-cpu-microcode" in matched["package_sets"]


def test_low_memory_beats_vendor_profile(amd_desktop_tree: Path) -> None:
    inventory = scan(amd_desktop_tree)
    inventory["memory"]["total_mib"] = 2048
    inventory["memory"]["total_kib"] = 2048 * 1024
    matched = match_profile(build_profile(inventory), load_ruleset())
    assert matched["profile_id"] == "low-memory"


def test_virtual_machine_wins_by_priority(amd_desktop_tree: Path) -> None:
    inventory = scan(amd_desktop_tree)
    inventory["host"]["virtualization"]["is_virtual_machine"] = True
    matched = match_profile(build_profile(inventory), load_ruleset())
    assert matched["profile_id"] == "virtual-machine"


def test_fallback_profile_used_for_unknown_machine(minimal_tree: Path) -> None:
    inventory = scan(minimal_tree)
    inventory["memory"]["total_mib"] = 8192
    inventory["memory"]["total_kib"] = 8192 * 1024
    matched = match_profile(build_profile(inventory), load_ruleset())
    assert matched["profile_id"] == "generic-x86-64"
    assert matched["fallback"] is True
    assert matched["matched_conditions"] == []


def test_low_memory_profile_matches_small_machine(minimal_tree: Path) -> None:
    matched = match_profile(_profile(minimal_tree), load_ruleset())
    assert matched["profile_id"] == "low-memory"
    assert matched["fallback"] is False


def test_matching_is_deterministic(intel_laptop_tree: Path) -> None:
    profile = _profile(intel_laptop_tree)
    ruleset = load_ruleset()
    assert match_profile(profile, ruleset) == match_profile(profile, ruleset)


def test_ruleset_validation_rejects_bad_operators() -> None:
    document = json.loads(default_ruleset_path().read_text(encoding="utf-8"))
    document["profiles"][0]["match"]["all"] = [{"field": "x", "op": "matches", "value": 1}]
    problems = validate_ruleset(document)
    assert any("op" in problem for problem in problems)


def test_ruleset_validation_rejects_duplicate_ids_and_unknown_package_sets() -> None:
    document = json.loads(default_ruleset_path().read_text(encoding="utf-8"))
    document["profiles"][1]["id"] = document["profiles"][0]["id"]
    document["profiles"][2]["package_sets"] = ["does-not-exist"]
    problems = validate_ruleset(document)
    assert any("duplicate" in problem for problem in problems)
    assert any("unknown package set" in problem for problem in problems)


def test_ruleset_validation_requires_fallback_to_be_unconditional() -> None:
    document = json.loads(default_ruleset_path().read_text(encoding="utf-8"))
    fallback = next(profile for profile in document["profiles"] if profile.get("fallback"))
    fallback["match"]["all"] = [{"field": "cpu.vendor", "op": "eq", "value": "intel"}]
    problems = validate_ruleset(document)
    assert any("fallback" in problem for problem in problems)


def test_missing_field_never_matches(minimal_tree: Path, tmp_path: Path) -> None:
    document = json.loads(default_ruleset_path().read_text(encoding="utf-8"))
    document["profiles"].insert(
        0,
        {
            "id": "impossible",
            "description": "References a field that does not exist.",
            "priority": 100,
            "match": {
                "all": [{"field": "does.not.exist", "op": "eq", "value": 1}]
            },
            "package_sets": [],
            "default_policy": "balanced",
            "notes": [],
        },
    )
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    matched = match_profile(_profile(minimal_tree), load_ruleset(path))
    entry = next(item for item in matched["evaluated_rules"] if item["rule"] == "impossible")
    assert entry["matched"] is False
    assert "does.not.exist is not present" in entry["conditions"]
    assert matched["profile_id"] != "impossible"
