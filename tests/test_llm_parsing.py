"""Tests for LLM response parsing edge cases (_parse_response in analysis/llm.py)."""

from magpie.analysis.llm import _parse_response


def test_valid_json():
    raw = '{"recommendation": "enter", "confidence": 0.75}'
    result = _parse_response(raw)
    assert result["recommendation"] == "enter"
    assert result["confidence"] == 0.75


def test_json_with_markdown_fences():
    raw = '```json\n{"recommendation": "avoid", "confidence": 0.3}\n```'
    result = _parse_response(raw)
    assert result["recommendation"] == "avoid"
    assert result["confidence"] == 0.3


def test_json_with_bare_fences():
    raw = '```\n{"recommendation": "hold"}\n```'
    result = _parse_response(raw)
    assert result["recommendation"] == "hold"


def test_json_with_unclosed_fence():
    """Fence opened but not properly closed — should still attempt parse."""
    raw = '```json\n{"recommendation": "enter"}\n'
    result = _parse_response(raw)
    assert result["recommendation"] == "enter"


def test_invalid_json_returns_empty():
    result = _parse_response("this is not json at all")
    assert result == {}


def test_empty_string_returns_empty():
    result = _parse_response("")
    assert result == {}


def test_whitespace_only_returns_empty():
    result = _parse_response("   \n\n  ")
    assert result == {}


def test_nested_objects():
    raw = '{"recommendation": "enter", "legs": [{"strike": 275}, {"strike": 285}]}'
    result = _parse_response(raw)
    assert result["recommendation"] == "enter"
    assert len(result["legs"]) == 2
    assert result["legs"][0]["strike"] == 275


def test_json_with_surrounding_whitespace():
    raw = '  \n  {"recommendation": "exit"}\n  '
    result = _parse_response(raw)
    assert result["recommendation"] == "exit"
