import json
import pytest


@pytest.fixture
def sample_config_data():
    return {
        "er605": {"host": "192.168.0.1", "username": "admin", "password": "secret"},
        "deco": {"host": "192.168.0.1", "password": "decopass"},
        "pihole": {"host": "192.168.0.10", "api_token": "abc123"},
    }


@pytest.fixture
def config_file(tmp_path, sample_config_data):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(sample_config_data))
    return p
