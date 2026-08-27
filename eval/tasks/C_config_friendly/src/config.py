"""Configuration loader."""
import json
from pathlib import Path


def load_config(path: str) -> dict:
    """Load JSON config from path."""
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text)