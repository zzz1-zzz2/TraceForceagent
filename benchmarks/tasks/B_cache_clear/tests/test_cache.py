from src.cache import Cache


def test_get_set():
    c = Cache()
    c.set("a", 1)
    assert c.get("a") == 1


def test_clear_removes_all():
    c = Cache()
    c.set("a", 1)
    c.set("b", 2)
    c.clear()
    assert c.get("a") is None
    assert c.get("b") is None


def test_clear_on_empty():
    c = Cache()
    c.clear()  # should not raise
    assert c.get("a") is None