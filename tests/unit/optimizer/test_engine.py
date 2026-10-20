"""Tests for the optimization plan engine and its CLI surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openqos.cli import main
from openqos.errors import OptimizationError
from openqos.hardware.scanner import scan
from openqos.optimizer.engine import build_plan, load_policies, render_plan, validate_policies
from openqos.optimizer.validate import validate_plan
from openqos.profiles.model import build_profile


def _plan(root: Path, policy: str = "balanced") -> dict:
    plan = build_plan(build_profile(scan(root)), policy=policy)
    assert validate_plan(plan) == []
    return plan


def _by_id(plan: dict) -> dict[str, dict]:
    return {decision["id"]: decision for decision in plan["decisions"]}


def test_policies_file_is_valid() -> None:
    document = load_policies()
    assert validate_policies(document) == []
    assert set(document["policies"]) == {"balanced", "performance", "power-saving"}


def test_balanced_plan_for_hybrid_laptop(intel_laptop_tree: Path) -> None:
    plan = _plan(intel_laptop_tree)
    assert plan["policy"] == "balanced"
    assert plan["selected_profile"]["profile_id"] == "hybrid-graphics-laptop"
    decisions = _by_id(plan)
    assert decisions["cpu-governor"]["status"] == "keep"
    assert decisions["cpu-energy-performance"]["status"] == "keep"
    assert decisions["platform-profile"]["status"] == "keep"
    assert decisions["graphics-driver"]["status"] == "keep"
    assert decisions["graphics-proprietary-driver"]["status"] == "manual"
    assert decisions["memory-swap"]["status"] == "plan"
    assert decisions["storage-trim"]["status"] == "plan"
    assert decisions["packages-intel-graphics"]["packages"] == [
        "mesa-dri-drivers",
        "intel-gpu-firmware",
    ]
    assert "packages-intel-wifi" in decisions
    assert decisions["packages-sof-audio"]["status"] == "plan"
    assert decisions["packages-power-management-laptop"]["status"] == "plan"
    assert "zram-generator" in plan["summary"]["packages"]


def test_performance_policy_changes_settings(intel_laptop_tree: Path) -> None:
    decisions = _by_id(_plan(intel_laptop_tree, "performance"))
    assert decisions["cpu-governor"]["value"] == "performance"
    assert decisions["cpu-governor"]["status"] == "plan"
    assert decisions["cpu-energy-performance"]["value"] == "performance"
    assert decisions["platform-profile"]["value"] == "performance"


def test_power_saving_policy_uses_low_power(intel_laptop_tree: Path) -> None:
    decisions = _by_id(_plan(intel_laptop_tree, "power-saving"))
    assert decisions["cpu-energy-performance"]["value"] == "power"
    assert decisions["platform-profile"]["value"] == "low-power"


def test_unsupported_setting_is_skipped_not_forced(amd_desktop_tree: Path) -> None:
    plan = _plan(amd_desktop_tree)
    decisions = _by_id(plan)
    assert decisions["platform-profile"]["status"] == "skip"
    assert "does not expose an ACPI platform profile" in decisions["platform-profile"]["rationale"]


def test_governor_not_offered_by_hardware_is_skipped(amd_desktop_tree: Path) -> None:
    inventory = scan(amd_desktop_tree)
    inventory["power"]["cpufreq"]["available_governors"] = ["powersave"]
    plan = build_plan(build_profile(inventory), policy="performance")
    decisions = _by_id(plan)
    assert decisions["cpu-governor"]["status"] == "skip"
    assert "not offered" in decisions["cpu-governor"]["rationale"]


def test_rotational_storage_skips_trim(amd_desktop_tree: Path) -> None:
    inventory = scan(amd_desktop_tree)
    for device in inventory["storage"]:
        device["rotational"] = True
    plan = build_plan(build_profile(inventory))
    decisions = _by_id(plan)
    assert decisions["storage-trim"]["status"] == "skip"
    assert "rotational" in decisions["storage-trim"]["rationale"]


def test_low_memory_plan_uses_zram(intel_laptop_tree: Path) -> None:
    inventory = scan(intel_laptop_tree)
    inventory["memory"]["total_mib"] = 2048
    plan = build_plan(build_profile(inventory))
    decisions = _by_id(plan)
    assert decisions["memory-swap"]["status"] == "plan"
    assert decisions["memory-swap"]["value"]["percent_of_ram"] == 50


def test_virtual_machine_plan_has_no_power_tuning(amd_desktop_tree: Path) -> None:
    inventory = scan(amd_desktop_tree)
    inventory["host"]["virtualization"]["is_virtual_machine"] = True
    plan = build_plan(build_profile(inventory))
    assert plan["selected_profile"]["profile_id"] == "virtual-machine"
    assert any("virtual machine" in notice for notice in plan["notices"])


def test_every_decision_has_rationale_and_planned_changes_are_reversible(
    intel_laptop_tree: Path,
) -> None:
    plan = _plan(intel_laptop_tree)
    for decision in plan["decisions"]:
        assert decision["rationale"]
        assert decision["evidence"]
        if decision["status"] == "plan":
            assert decision["rollback"], decision["id"]
            assert decision["reversible"] is True
    assert plan["summary"]["all_reversible"] is True


def test_plan_is_deterministic_except_timestamp(intel_laptop_tree: Path) -> None:
    first = _plan(intel_laptop_tree)
    second = _plan(intel_laptop_tree)
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second


def test_unknown_policy_is_rejected(intel_laptop_tree: Path) -> None:
    with pytest.raises(OptimizationError):
        build_plan(build_profile(scan(intel_laptop_tree)), policy="turbo")


def test_plan_validation_catches_missing_rollback(intel_laptop_tree: Path) -> None:
    plan = _plan(intel_laptop_tree)
    planned = next(decision for decision in plan["decisions"] if decision["status"] == "plan")
    planned["rollback"] = None
    assert any("without a rollback" in problem for problem in validate_plan(plan))


def test_render_plan_text(intel_laptop_tree: Path) -> None:
    text = render_plan(_plan(intel_laptop_tree))
    assert "OpenQOS optimisation plan (policy: balanced)" in text
    assert "matched conditions:" in text
    assert "rollback:" in text


def test_cli_profile_and_optimize_commands(
    intel_laptop_tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inventory_path = tmp_path / "inventory.json"
    session = __import__("openqos.hardware.scanner", fromlist=["scan"])
    inventory_path.write_text(
        json.dumps(session.scan(intel_laptop_tree, privacy=True)), encoding="utf-8"
    )

    assert (
        main(["profile", "build", "-i", str(inventory_path), "-o", str(tmp_path / "p.json")])
        == 0
    )
    capsys.readouterr()
    assert main(["profile", "validate", str(tmp_path / "p.json")]) == 0
    assert "valid hardware profile" in capsys.readouterr().out

    assert main(["profile", "explain", "-i", str(inventory_path)]) == 0
    explain = capsys.readouterr().out
    assert "hybrid-graphics-laptop" in explain
    assert "not matched:" in explain

    assert main(["optimize", "-i", str(inventory_path), "--format", "json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert validate_plan(plan) == []
    assert plan["policy"] == "balanced"

    assert main(["optimize", "-i", str(inventory_path), "--policy", "power-saving"]) == 0
    text = capsys.readouterr().out
    assert "power-saving" in text


_SAMPLES = Path(__file__).resolve().parents[3] / "docs" / "samples"


def test_committed_samples_are_valid() -> None:
    from openqos.optimizer.validate import load_json, validate_profile_document

    profile = load_json(_SAMPLES / "normalized-profile.json")
    assert validate_profile_document(profile) == []
    plan = load_json(_SAMPLES / "optimization-plan.json")
    assert validate_plan(plan) == []
    assert plan["selected_profile"]["profile_id"] == "hybrid-graphics-laptop"


def test_cli_optimize_rejects_bad_inventory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "1.0.0"}), encoding="utf-8")
    assert main(["optimize", "-i", str(bad)]) == 2
    assert "openqos: error" in capsys.readouterr().err
