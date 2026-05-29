import json
import pytest
from src.config import load_config, Config, ER605Config, DecoConfig, PiholeConfig


def test_load_config_returns_typed_config(config_file):
    cfg = load_config(config_file)
    assert isinstance(cfg, Config)
    assert isinstance(cfg.er605, ER605Config)
    assert isinstance(cfg.deco, DecoConfig)
    assert isinstance(cfg.pihole, PiholeConfig)


def test_load_config_er605_fields(config_file):
    cfg = load_config(config_file)
    assert cfg.er605.host == "192.168.0.1"
    assert cfg.er605.username == "admin"
    assert cfg.er605.password == "secret"


def test_load_config_deco_fields(config_file):
    cfg = load_config(config_file)
    assert cfg.deco.host == "192.168.0.1"
    assert cfg.deco.password == "decopass"


def test_load_config_pihole_fields(config_file):
    cfg = load_config(config_file)
    assert cfg.pihole.host == "192.168.0.10"
    assert cfg.pihole.api_token == "abc123"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.json")


def test_load_config_missing_er605_key_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"deco": {"host": "x", "password": "y"}, "pihole": {"host": "z", "api_token": "w"}}))
    with pytest.raises(KeyError):
        load_config(p)
