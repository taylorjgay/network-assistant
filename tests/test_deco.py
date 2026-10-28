import threading
import time

import pytest
from unittest.mock import patch
import src.tools.deco as deco_module
from src.tools.deco import DecoClient


@pytest.fixture(autouse=True)
def clear_mesh_cache():
    deco_module._mesh_cache = None


@pytest.fixture
def client():
    return DecoClient(host="192.168.0.100", password="testpass")


CLIENT_LIST_PAYLOAD = {
    "error_code": 0,
    "result": {
        "client_list": [
            {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ip": "192.168.68.100",
                "name": "Taylors-iPhone",
                "type": "wireless",
                "wire_type": "wifi5",
                "belong_to": "AA:11:22:33:44:55",
            }
        ]
    },
}

DEVICE_LIST_PAYLOAD = {
    "error_code": 0,
    "result": {
        "device_list": [
            {
                "mac": "AA:11:22:33:44:55",
                "device_ip": "192.168.0.100",
                "nickname": "Office",
                "role": "master",
                "inet_status": "offline",
                "inet_error_msg": "with_ip_dynamic_ip",
                "connection_type": None,
                "signal_strength": {},
            },
            {
                "mac": "BB:11:22:33:44:55",
                "device_ip": "192.168.0.101",
                "nickname": "Basement",
                "role": "slave",
                "group_status": "connected",
                "inet_status": "offline",
                "connection_type": "wired",
                "signal_strength": {"band5": -60},
            },
            {
                "mac": "CC:11:22:33:44:55",
                "device_ip": "192.168.0.102",
                "nickname": "Bedroom",
                "role": "slave",
                "group_status": "connected",
                "inet_status": "offline",
                "connection_type": "wireless",
                "signal_strength": {"band5": -65},
            },
        ]
    },
}


def test_get_connected_clients_success(client):
    with patch.object(client, "_request", return_value=CLIENT_LIST_PAYLOAD):
        result = client.get_connected_clients()
    assert result["success"] is True
    assert result["count"] == 1
    assert result["clients"][0]["hostname"] == "Taylors-iPhone"
    assert result["clients"][0]["mac"] == "AA:BB:CC:DD:EE:FF"
    assert result["clients"][0]["ip"] == "192.168.68.100"
    assert result["clients"][0]["deco_node_mac"] == "AA:11:22:33:44:55"
    assert result["clients"][0]["band"] == "wifi5"


def test_get_connected_clients_fallback_hostname(client):
    """Devices without a name field fall back to MAC as hostname."""
    payload = {
        "error_code": 0,
        "result": {"client_list": [{"mac": "DE:AD:BE:EF:00:01", "ip": "192.168.68.50"}]},
    }
    with patch.object(client, "_request", return_value=payload):
        result = client.get_connected_clients()
    assert result["clients"][0]["hostname"] == "DE:AD:BE:EF:00:01"


def test_get_mesh_health_success(client):
    with patch.object(client, "_request", return_value=DEVICE_LIST_PAYLOAD):
        result = client.get_mesh_health()
    assert result["success"] is True
    assert result["node_count"] == 3
    primary = next(n for n in result["nodes"] if n["is_primary"])
    assert primary["mac"] == "AA:11:22:33:44:55"
    assert primary["nickname"] == "Office"
    assert primary["mesh_status"] == "connected"
    wireless = next(n for n in result["nodes"] if n["backhaul"] == "wireless")
    assert wireless["signal_level_dbm"] == -65
    assert wireless["inet_status"] == "offline"


def test_get_connected_clients_auth_failure(client):
    with patch.object(client, "_request", side_effect=Exception("Deco authentication failed")):
        result = client.get_connected_clients()
    assert result["success"] is False
    assert "suggestion" in result
    assert "attempted" in result


def test_get_mesh_health_auth_failure(client):
    with patch.object(client, "_request", side_effect=Exception("Deco authentication failed")):
        result = client.get_mesh_health()
    assert result["success"] is False
    assert "suggestion" in result


# --- One Deco login at a time, and a short shared mesh result ---

DEVICE_LIST = {"error_code": 0, "result": {"device_list": [
    {"mac": "60-83-E7-1C-DA-FC", "device_ip": "192.168.0.104", "nickname": "Office", "role": "master"},
]}}


def test_concurrent_mesh_health_calls_share_one_fetch():
    """The Network page asks for /mesh and /devices at once; both used to log in and collide."""
    calls = []

    def slow_request(resource, form, client):
        calls.append((resource, form))
        time.sleep(0.05)  # long enough for the other thread to arrive while this one holds the lock
        return DEVICE_LIST if form == "device_list" else {"result": {}}

    results = []
    with patch.object(DecoClient, "_request", side_effect=slow_request):
        threads = [threading.Thread(target=lambda: results.append(
            DecoClient(host="192.168.0.104", password="x").get_mesh_health())) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert [r["success"] for r in results] == [True, True, True]
    assert calls.count(("device", "device_list")) == 1


def test_mesh_health_refetches_after_ttl(monkeypatch):
    with patch.object(DecoClient, "_request", return_value=DEVICE_LIST) as req:
        DecoClient(host="192.168.0.104", password="x").get_mesh_health()
        monkeypatch.setattr(deco_module, "_mesh_cache", (time.monotonic() - deco_module._MESH_TTL - 1, deco_module._mesh_cache[1]))
        DecoClient(host="192.168.0.104", password="x").get_mesh_health()
    assert [c.args[:2] for c in req.call_args_list].count(("device", "device_list")) == 2


def test_failed_mesh_health_is_not_cached():
    with patch.object(DecoClient, "_request", side_effect=Exception("empty reply")):
        assert DecoClient(host="192.168.0.104", password="x").get_mesh_health()["success"] is False
    assert deco_module._mesh_cache is None
