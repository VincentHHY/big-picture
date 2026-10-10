"""Offline regression tests for report-row usability classification."""

import pytest

from evals.fixtures.report_builder import SUSPECT_FLAGS, is_usable


def test_is_usable_rejects_empty_values_and_suspect_flags():
    """Both independent rejection conditions must take precedence."""
    ordinary_flag = object()

    assert is_usable({"flag": ordinary_flag, "value": ""}) is False
    for suspect_flag in SUSPECT_FLAGS:
        assert is_usable({"flag": suspect_flag, "value": "present"}) is False


@pytest.mark.parametrize("value", ["0", 0, None])
def test_is_usable_accepts_nonempty_values_without_string_coercion(value):
    """Only the empty-string boundary is rejected; other value types pass through."""
    assert is_usable({"flag": object(), "value": value}) is True


@pytest.mark.parametrize("row", [{"flag": object()}, {"value": "present"}, None])
def test_is_usable_propagates_invalid_row_shape_errors(row):
    """The helper requires mapping-style rows with both documented fields."""
    with pytest.raises((KeyError, TypeError)):
        is_usable(row)
