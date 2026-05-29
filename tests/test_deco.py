import base64
import json
import pytest
import respx
import httpx
from unittest.mock import patch, MagicMock
from src.tools.deco import DecoClient


@pytest.fixture
def client():
    return DecoClient(host="192.168.0.1", password="decopass")


def make_mock_encrypted_response(payload: dict) -> str:
    """Return a base64-encoded fake encrypted response for testing."""
    return base64.b64encode(json.dumps(payload).encode()).decode()


@respx.mock
def test_get_connected_clients_success(client):
    client_list_payload = {
        "error_code": 0,
        "result": {
            "client_list": [
                {
                    "mac": "AA:BB:CC:DD:EE:FF",
                    "ip": "192.168.68.100",
                    "name": "Taylors-iPhone",
                    "device_type": "phone",
                    "up_speed": 0,
                    "down_speed": 102400,
                    "owner_id": "",
                    "guest": False,
                    "type": "wireless",
                    "wire_type": "wifi5",
                    "belong_to": "AA:11:22:33:44:55",
                }
            ]
        }
    }
    with patch.object(client, "_authenticated_request", return_value=client_list_payload):
        result = client.get_connected_clients()
    assert result["success"] is True
    assert len(result["clients"]) == 1
    assert result["clients"][0]["hostname"] == "Taylors-iPhone"
    assert result["clients"][0]["mac"] == "AA:BB:CC:DD:EE:FF"
    assert result["clients"][0]["ip"] == "192.168.68.100"


@respx.mock
def test_get_mesh_health_success(client):
    device_list_payload = {
        "error_code": 0,
        "result": {
            "device_list": [
                {
                    "mac": "AA:11:22:33:44:55",
                    "device_ip": "192.168.0.1",
                    "inet_status": "online",
                    "master": True,
                    "bssid_5g": "AA:11:22:33:44:56",
                    "connection_type": "wired",
                    "signal_level": {"band5_0": 0},
                },
                {
                    "mac": "BB:11:22:33:44:55",
                    "device_ip": "192.168.0.2",
                    "inet_status": "online",
                    "master": False,
                    "connection_type": "wired",
                    "signal_level": {"band5_0": 0},
                },
                {
                    "mac": "CC:11:22:33:44:55",
                    "device_ip": "192.168.0.3",
                    "inet_status": "online",
                    "master": False,
                    "connection_type": "wireless",
                    "signal_level": {"band5_0": -65},
                },
            ]
        }
    }
    with patch.object(client, "_authenticated_request", return_value=device_list_payload):
        result = client.get_mesh_health()
    assert result["success"] is True
    assert len(result["nodes"]) == 3
    wireless_node = next(n for n in result["nodes"] if n["backhaul"] == "wireless")
    assert wireless_node["signal_level_dbm"] == -65


def test_get_connected_clients_auth_failure(client):
    with patch.object(client, "_authenticated_request", side_effect=Exception("auth failed")):
        result = client.get_connected_clients()
    assert result["success"] is False
    assert "suggestion" in result
