import pytest
from src.math_utils import safe_divide, average


def test_safe_divide_normal():
    assert safe_divide(10, 2) == 5.0


def test_safe_divide_by_zero():
    assert safe_divide(10, 0) == 0.0


def test_average_uses_safe_divide():
    assert average([10, 20, 30]) == 20.0


def test_average_empty_raises():
    with pytest.raises(ValueError):
        average([])