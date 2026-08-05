"""Tolerant JSON extraction at the model boundary (#51)."""

from jarviscore.kernel.subagent import _extract_json_object


def test_valid_json_still_parses():
    assert _extract_json_object('{"a": 1, "b": [1, 2]}') == {"a": 1, "b": [1, 2]}


def test_trailing_comma_in_object():
    assert _extract_json_object('{"query": "x", "top_k": 5,}') == {"query": "x", "top_k": 5}


def test_trailing_comma_in_array():
    assert _extract_json_object('{"items": [1, 2, 3,]}') == {"items": [1, 2, 3]}


def test_python_literal_dict():
    out = _extract_json_object("{'query': 'x', 'flag': True, 'n': None}")
    assert out == {"query": "x", "flag": True, "n": None}


def test_python_literal_nested():
    out = _extract_json_object("{'a': {'b': False}, 'c': [1, 2]}")
    assert out == {"a": {"b": False}, "c": [1, 2]}


def test_python_literal_non_dict_rejected():
    assert _extract_json_object("[1, 2, 3]") is None


def test_prose_still_rejected():
    assert _extract_json_object("call the tool with query x") is None


def test_code_execution_not_possible():
    """literal_eval must not evaluate expressions."""
    assert _extract_json_object("{'a': __import__('os').getcwd()}") is None


def test_multiline_code_value_still_works():
    text = '{"code": "for i in range(3):\n    print(i)"}'
    out = _extract_json_object(text)
    assert out is not None and "print" in out["code"]
