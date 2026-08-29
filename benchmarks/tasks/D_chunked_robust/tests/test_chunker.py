import pytest
from src.chunker import list_chunked


def test_chunk_basic():
    assert list_chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunk_size_one():
    assert list_chunked([1, 2, 3], 1) == [[1], [2], [3]]


def test_chunk_empty():
    assert list_chunked([], 3) == []


def test_chunk_size_zero_or_negative_raises():
    with pytest.raises(ValueError):
        list_chunked([1, 2], 0)
    with pytest.raises(ValueError):
        list_chunked([1, 2], -1)