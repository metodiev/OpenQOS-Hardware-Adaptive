"""Tests for the live-session status report."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from openqos.cli import main
from openqos.status import build_status, load_state, render_status, write_summary

_SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "samples"


def _state_directory(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    shutil.copy2(_SAMPLES / "hardware-profile.json", state / "inventory.json")
    shutil.copy2(_SAMPLES / "normalized-profile.json", state / "profile.json")
    shutil.copy2(_SAMPLES / "optimization-plan.json", state / "plan.json")
    return state


def test_empty_state_is_reported(tmp_path: Path) -> None:
    status = build_status(load_state(tmp_path / "missing"))
    assert status["has_inventory"] is False
    assert "no hardware scan has run yet" in render_status(status)


def test_status_from_samples(tmp_path: Path) -> None:
    status = build_status(load_state(_state_directory(tmp_path)))
    assert status["has_inventory"] and status["has_profile"] and status["has_plan"]
    assert status["machine"]["form_factor"] == "laptop"
    assert status["profile_id"] == "hybrid-graphics-laptop"
    assert status["policy"] == "balanced"
    assert status["by_status"]["plan"] >= 1
    assert "zram-generator" in status["packages"]
    assert status["issues"]

    text = render_status(status)
    assert "OpenQOS hardware report" in text
    assert "hybrid-graphics-laptop" in text
    assert "Nothing has been changed on this system." in text


def test_write_summary(tmp_path: Path) -> None:
    status = build_status(load_state(_state_directory(tmp_path)))
    path = write_summary(status, tmp_path / "logs" / "summary.txt")
    assert path.is_file()
    assert "OpenQOS hardware report" in path.read_text(encoding="utf-8")


def test_cli_status_json_and_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _state_directory(tmp_path)
    summary = tmp_path / "summary.txt"
    assert (
        main(
            [
                "status",
                "--state-dir",
                str(state),
                "--format",
                "json",
                "--write-summary",
                str(summary),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile_id"] == "hybrid-graphics-laptop"
    assert summary.is_file()


def test_cli_status_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["status", "--state-dir", str(_state_directory(tmp_path))]) == 0
    assert "OpenQOS hardware report" in capsys.readouterr().out
