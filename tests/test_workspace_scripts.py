"""Tests for workspace/lib/ scripts -- pure utility functions."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _import_script(name: str):
    """Import a workspace script by name."""
    script_path = Path(__file__).parent.parent / "workspace" / "lib" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, str(script_path))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kelly_mod = _import_script("kelly_size")


# ── kelly_size.kelly ─────────────────────────────────────────────


def test_kelly_positive_edge():
    result = kelly_mod.kelly(0.10, 1.0, 500, fraction=0.25)
    assert result["bet_size_usd"] > 0
    assert result["full_kelly"] > 0
    assert result["fractional_kelly"] > 0


def test_kelly_zero_edge():
    result = kelly_mod.kelly(0.0, 1.0, 500)
    assert result["bet_size_usd"] == 0


def test_kelly_negative_edge():
    result = kelly_mod.kelly(-0.10, 1.0, 500)
    assert result["bet_size_usd"] == 0
    assert result["full_kelly"] < 0


def test_kelly_fraction_reduces_bet():
    full = kelly_mod.kelly(0.10, 1.0, 500, fraction=1.0)
    quarter = kelly_mod.kelly(0.10, 1.0, 500, fraction=0.25)
    assert quarter["bet_size_usd"] < full["bet_size_usd"]


def test_kelly_risk_of_ruin_bounded():
    result = kelly_mod.kelly(0.10, 1.0, 500, fraction=0.25)
    assert 0 <= result["risk_of_ruin"] <= 1
