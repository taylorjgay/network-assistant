import threading
import time

import pytest
from unittest.mock import patch
import src.tools.deco as deco_module
from src.tools.deco import DecoClient


@pytest.fixture(autouse=True)
def clear_mesh_cache():
    deco_module._cache.clear()


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
        deco_module._cache["mesh"] = (time.monotonic() - deco_module._MESH_TTL - 1, deco_module._cache["mesh"][1])
        DecoClient(host="192.168.0.104", password="x").get_mesh_health()
    assert [c.args[:2] for c in req.call_args_list].count(("device", "device_list")) == 2


def test_failed_mesh_health_is_not_cached():
    with patch.object(DecoClient, "_request", side_effect=Exception("empty reply")):
        assert DecoClient(host="192.168.0.104", password="x").get_mesh_health()["success"] is False
    assert "mesh" not in deco_module._cache


# --- Connected clients: client_list needs a device_mac param (captured live 2026-10-28) ---

NODES = {"error_code": 0, "result": {"device_list": [
    {"mac": "60-83-E7-1C-DA-FC", "nickname": "Office", "role": "master"},
    {"mac": "60-83-E7-1C-D6-74", "nickname": "basement", "role": "slave"},
]}}
CLIENTS_BY_NODE = {
    "60-83-E7-1C-DA-FC": [{"mac": "88-A2-9E-EF-28-33", "ip": "192.168.0.183", "name": "cm9zaWUtZGlzcGxheQ==",
                           "wire_type": "wireless", "connection_type": "band5", "client_type": "iot_device",
                           "interface": "main", "online": True, "access_host": "1"}],
    "60-83-E7-1C-D6-74": [{"mac": "B8-27-EB-23-CB-D0", "ip": "192.168.0.200", "name": "cGlob2xl",
                           "wire_type": "wired", "connection_type": "wired", "client_type": "other",
                           "interface": "main", "online": True, "access_host": "1"}],
}


def _deco_router(per_node_fails=False):
    seen_params = []

    def request(resource, form, client, params=None):
        if form == "device_list":
            return NODES
        seen_params.append(params)
        mac = (params or {}).get("device_mac")
        if mac is None:
            raise Exception("Deco returned error: attempt to index field 'device_mac' (a nil value)")
        if mac == "default":
            return {"error_code": 0, "result": {"client_list": [c for cl in CLIENTS_BY_NODE.values() for c in cl]}}
        if per_node_fails:
            raise Exception("empty reply")
        return {"error_code": 0, "result": {"client_list": CLIENTS_BY_NODE[mac]}}

    return request, seen_params


def test_connected_clients_places_each_client_on_its_node(client):
    request, seen = _deco_router()
    with patch.object(client, "_request", side_effect=request):
        result = client.get_connected_clients()
    assert result["success"] is True and result["count"] == 2
    assert seen == [{"device_mac": "60-83-E7-1C-DA-FC"}, {"device_mac": "60-83-E7-1C-D6-74"}]
    assert result["clients"][0] == {
        "hostname": "rosie-display", "mac": "88:a2:9e:ef:28:33", "ip": "192.168.0.183",
        "deco_node": "Office", "deco_node_mac": "60:83:e7:1c:da:fc", "connection": "wireless",
        "band": "5GHz", "client_type": "iot_device", "network": "main", "online": True,
    }
    wired = result["clients"][1]
    assert (wired["hostname"], wired["deco_node"], wired["connection"], wired["band"]) == ("pihole", "basement", "wired", None)


def test_connected_clients_falls_back_to_unplaced_list(client):
    request, seen = _deco_router(per_node_fails=True)
    with patch.object(client, "_request", side_effect=request):
        result = client.get_connected_clients()
    assert result["success"] is True and result["count"] == 2
    assert seen[-1] == {"device_mac": "default"}
    assert {c["deco_node"] for c in result["clients"]} == {None}


def test_decode_name_leaves_plain_names_alone():
    assert deco_module._decode_name("cm9zaWUtZGlzcGxheQ==") == "rosie-display"
    assert deco_module._decode_name("Taylor's iPhone") == "Taylor's iPhone"
    assert deco_module._decode_name(None) is None
