"""Tests for inventory validation and CLI behaviour."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openqos.cli import main
from openqos.errors import SchemaError
from openqos.hardware.scanner import scan
from openqos.hardware.validate import load_document, validate_document


def test_load_document_rejects_invalid_json(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(SchemaError):
        load_document(broken)


def test_structural_validation_catches_missing_fields(minimal_tree: Path) -> None:
    document = scan(minimal_tree)
    document.pop("power")
    problems = validate_document(document)
    assert any("power" in problem for problem in problems)


def test_structural_validation_catches_wrong_types(minimal_tree: Path) -> None:
    document = scan(minimal_tree)
    document["storage"] = {"not": "a list"}
    problems = validate_document(document)
    assert any("storage" in problem for problem in problems)


def test_structural_validation_catches_version_mismatch(minimal_tree: Path) -> None:
    document = scan(minimal_tree)
    document["schema_version"] = "0.0.1"
    problems = validate_document(document)
    assert any("schema_version" in problem for problem in problems)


def test_cli_scan_stdout(minimal_tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["hardware", "scan", "--root", str(minimal_tree)])
    captured = capsys.readouterr()
    assert exit_code == 0
    document = json.loads(captured.out)
    assert document["schema_version"] == "1.0.0"


def test_cli_scan_writes_file_with_summary(
    intel_laptop_tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "nested" / "profile.json"
    exit_code = main(["hardware", "scan", "--root", str(intel_laptop_tree), "-o", str(output)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert output.is_file()
    assert "hardware summary" in captured.out
    assert "12th Gen Intel" in captured.out
    assert load_document(output)["cpu"]["logical_cpus"] == 8


def test_cli_validate_valid(
    intel_laptop_tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "profile.json"
    main(["hardware", "scan", "--root", str(intel_laptop_tree), "-o", str(output)])
    capsys.readouterr()
    assert main(["hardware", "validate", str(output)]) == 0
    assert "valid hardware inventory" in capsys.readouterr().out


def test_cli_validate_invalid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "profile.json"
    broken.write_text(json.dumps({"schema_version": "1.0.0"}), encoding="utf-8")
    assert main(["hardware", "validate", str(broken)]) == 1
    assert "missing required field" in capsys.readouterr().err


def test_cli_schema_lists_versions(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["hardware", "schema"]) == 0
    captured = capsys.readouterr()
    assert "1.0.0" in captured.out
    assert "schema_version" in captured.out


def test_cli_image_plan_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["image", "plan"]) == 0
    out = capsys.readouterr().out
    assert "Fedora Linux" in out or "fedora-44" in out
    assert "KDE-Desktop-Live" in out


def test_cli_image_plan_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["image", "plan", "--format", "json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["environment"]["kiwi_descriptions"]["commit"]
    assert plan["environment"]["kiwi_descriptions"]["image_type"] == "iso"


def test_cli_image_plan_unknown_profile(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["image", "plan", "--profile", "nope"]) == 2
    assert "unknown image profile" in capsys.readouterr().err


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "openqos" in capsys.readouterr().out
