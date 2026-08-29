"""Math utilities."""


def safe_divide(a: float, b: float) -> float:
    """Divide a by b. Returns 0 if b is 0."""
    return a / b  # BUG: should handle b == 0


def average(values: list[float]) -> float:
    if not values:
        raise ValueError("empty")
    return safe_divide(sum(values), len(values))