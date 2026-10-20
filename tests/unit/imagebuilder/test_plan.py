"""Tests for the image build plan."""

from __future__ import annotations

import pytest

from openqos.errors import ImageBuildError
from openqos.imagebuilder.plan import (
    BASE_IMAGE_PROFILE,
    FEDORA_RELEASE,
    KIWI_DESCRIPTIONS_COMMIT,
    build_plan,
    render_plan,
)


def test_plan_pins_inputs() -> None:
    plan = build_plan()
    environment = plan["environment"]
    assert environment["base_distribution"] == f"fedora-{FEDORA_RELEASE}"
    kiwi = environment["kiwi_descriptions"]
    assert kiwi["commit"] == KIWI_DESCRIPTIONS_COMMIT
    assert len(kiwi["commit"]) == 40
    assert kiwi["image_profile"] == BASE_IMAGE_PROFILE
    assert kiwi["image_type"] == "iso"


def test_plan_is_json_serialisable() -> None:
    import json

    plan = build_plan(profile="generic", work_directory=".work/custom")
    payload = json.dumps(plan)
    assert ".work/custom/kiwi-descriptions" in payload


def test_plan_rejects_unknown_profile() -> None:
    with pytest.raises(ImageBuildError):
        build_plan(profile="titanium")


def test_render_plan_contains_steps_and_commands() -> None:
    text = render_plan(build_plan())
    assert "steps:" in text
    assert "kiwi-ng" not in text  # the wrapper is used, not kiwi-ng directly
    assert "./kiwi-build" in text
    assert KIWI_DESCRIPTIONS_COMMIT in text
