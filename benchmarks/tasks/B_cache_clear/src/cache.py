"""Simple in-memory Cache."""


class Cache:
    def __init__(self):
        self._store: dict = {}

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value) -> None:
        self._store[key] = value

    # TODO: implement clear() method