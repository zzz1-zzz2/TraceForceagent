"""Chunking utilities."""


def list_chunked(items: list, size: int) -> list[list]:
    """Split items into chunks of given size."""
    chunks = []
    for i in range(0, len(items), size):
        chunks.append(items[i:i + size])
    return chunks