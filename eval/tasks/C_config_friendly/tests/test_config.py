import json
import pytest
from src.config import load_config


def test_load_valid(tmp_path):
    p = tmp_path / "ok.json"
    p.write_text(json.dumps({"host": "localhost", "port": 8080}))
    assert load_config(str(p)) == {"host": "localhost", "port": 8080}


def test_load_missing_file_returns_empty(tmp_path):
    # Missing config file should return {} instead of raising
    assert load_config(str(tmp_path / "nope.json")) == {}


def test_load_partial_returns_defaults(tmp_path):
    p = tmp_path / "partial.json"
    p.write_text(json.dumps({"host": "localhost"}))
    cfg = load_config(str(p))
    assert cfg.get("host") == "localhost"
    assert cfg.get("port") == 8080  # default