import pytest
from unittest.mock import patch
from src.tools.wan_health import WANHealthClient
from src.tools.er605 import ER605Client


@pytest.fixture
def client():
    return WANHealthClient(host="192.168.0.1", username="admin", password="secret")


def _iface_result(wan1_up=True, wan2_up=True):
    return {
        "success": True,
        "interfaces": [
            {"name": "WAN1", "up": wan1_up,
             "ip": "192.168.1.70" if wan1_up else "",
             "gateway": "192.168.1.254", "proto": "dhcp", "dns1": "8.8.8.8"},
            {"name": "WAN2", "up": wan2_up,
             "ip": "192.168.12.153" if wan2_up else "",
             "gateway": "192.168.12.1", "proto": "dhcp", "dns1": "8.8.8.8"},
        ],
    }


GOOD_PROBE = {
    "targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"],
    "avg_latency_ms": 14.2,
    "packet_loss_pct": 0.0,
}
DEGRADED_LOSS_PROBE = {
    "targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"],
    "avg_latency_ms": 14.2,
    "packet_loss_pct": 10.0,
}
DEGRADED_LATENCY_PROBE = {
    "targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"],
    "avg_latency_ms": 200.0,
    "packet_loss_pct": 0.0,
}


def test_get_wan_health_success(client):
    with patch.object(ER605Client, "get_wan_status", return_value=_iface_result()):
        with patch("src.tools.wan_health._probe", return_value=GOOD_PROBE):
            result = client.get_wan_health()

    assert result["success"] is True
    assert result["active_wan"] == "WAN1"
    assert result["wan1"]["link"] == "up"
    assert result["wan1"]["ip"] == "192.168.1.70"
    assert result["wan2"]["link"] == "up"
    assert result["probe"]["avg_latency_ms"] == 14.2
    assert result["probe"]["packet_loss_pct"] == 0.0
    assert result["degraded"] is False


def test_get_wan_health_degraded_packet_loss(client):
    with patch.object(ER605Client, "get_wan_status", return_value=_iface_result()):
        with patch("src.tools.wan_health._probe", return_value=DEGRADED_LOSS_PROBE):
            result = client.get_wan_health()

    assert result["success"] is True
    assert result["degraded"] is True


def test_get_wan_health_degraded_latency(client):
    with patch.object(ER605Client, "get_wan_status", return_value=_iface_result()):
        with patch("src.tools.wan_health._probe", return_value=DEGRADED_LATENCY_PROBE):
            result = client.get_wan_health()

    assert result["success"] is True
    assert result["degraded"] is True


def test_get_wan_health_wan2_active_failover(client):
    with patch.object(ER605Client, "get_wan_status", return_value=_iface_result(wan1_up=False, wan2_up=True)):
        with patch("src.tools.wan_health._probe", return_value=GOOD_PROBE):
            result = client.get_wan_health()

    assert result["success"] is True
    assert result["active_wan"] == "WAN2"
    assert result["wan1"]["link"] == "down"
    assert result["wan1"]["ip"] is None


def test_get_wan_health_er605_auth_failure(client):
    with patch.object(ER605Client, "get_wan_status", return_value={
        "success": False,
        "error": "ER605 authentication failed: bad password",
        "suggestion": "Check er605.username and er605.password in config.json",
        "attempted": "192.168.0.1",
    }):
        result = client.get_wan_health()

    assert result["success"] is False
    assert "authentication failed" in result["error"]


def test_get_wan_health_partial_interface_data(client):
    # Only WAN1 present (WAN2 absent from interfaces list)
    partial = {
        "success": True,
        "interfaces": [
            {"name": "WAN1", "up": True, "ip": "192.168.1.70", "gateway": "192.168.1.254",
             "proto": "dhcp", "dns1": "8.8.8.8"},
        ],
    }
    with patch.object(ER605Client, "get_wan_status", return_value=partial):
        with patch("src.tools.wan_health._probe", return_value=GOOD_PROBE):
            result = client.get_wan_health()

    assert result["success"] is True
    assert result["wan1"]["link"] == "up"
    assert result["wan2"] is None


# --- compare_wan_health ---

GOOD_PROBE_WAN1 = {"targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"], "avg_latency_ms": 14.2, "packet_loss_pct": 0.0}
GOOD_PROBE_WAN2 = {"targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"], "avg_latency_ms": 42.1, "packet_loss_pct": 0.0}
DEGRADED_PROBE = {"targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"], "avg_latency_ms": 200.0, "packet_loss_pct": 20.0}


def test_compare_wan_health_wan1_healthier(client):
    with patch.object(ER605Client, "get_wan_policy", return_value={"success": True, "primary_wan": "WAN1"}):
        with patch.object(ER605Client, "set_wan_priority", return_value={"success": True}) as mock_set:
            with patch("src.tools.wan_health._probe", side_effect=[GOOD_PROBE_WAN1, GOOD_PROBE_WAN2]):
                with patch("src.tools.wan_health.time.sleep"):
                    result = client.compare_wan_health()

    assert result["success"] is True
    assert result["original_policy"] == "WAN1"
    assert result["wan1_probe"]["avg_latency_ms"] == 14.2
    assert result["wan1_probe"]["degraded"] is False
    assert result["wan2_probe"]["avg_latency_ms"] == 42.1
    assert result["wan2_probe"]["degraded"] is False
    assert "WAN1" in result["recommendation"]
    assert result["restored"] is True
    assert mock_set.call_count == 3
    calls = [c.args[0] for c in mock_set.call_args_list]
    assert calls == ["WAN1", "WAN2", "WAN1"]


def test_compare_wan_health_wan2_healthier(client):
    with patch.object(ER605Client, "get_wan_policy", return_value={"success": True, "primary_wan": "WAN1"}):
        with patch.object(ER605Client, "set_wan_priority", return_value={"success": True}):
            with patch("src.tools.wan_health._probe", side_effect=[DEGRADED_PROBE, GOOD_PROBE_WAN2]):
                with patch("src.tools.wan_health.time.sleep"):
                    result = client.compare_wan_health()

    assert result["success"] is True
    assert result["wan1_probe"]["degraded"] is True
    assert result["wan2_probe"]["degraded"] is False
    assert "WAN2" in result["recommendation"]


def test_compare_wan_health_both_degraded(client):
    with patch.object(ER605Client, "get_wan_policy", return_value={"success": True, "primary_wan": "WAN1"}):
        with patch.object(ER605Client, "set_wan_priority", return_value={"success": True}):
            with patch("src.tools.wan_health._probe", side_effect=[DEGRADED_PROBE, DEGRADED_PROBE]):
                with patch("src.tools.wan_health.time.sleep"):
                    result = client.compare_wan_health()

    assert result["success"] is True
    assert "Both WANs degraded" in result["recommendation"]


def test_compare_wan_health_restore_on_probe_failure(client):
    with patch.object(ER605Client, "get_wan_policy", return_value={"success": True, "primary_wan": "WAN1"}):
        with patch.object(ER605Client, "set_wan_priority", return_value={"success": True}) as mock_set:
            with patch("src.tools.wan_health._probe", side_effect=Exception("ping failed")):
                with patch("src.tools.wan_health.time.sleep"):
                    result = client.compare_wan_health()

    assert result["success"] is False
    assert result["restored"] is True
    # WAN1 switch (call 1) + WAN1 restore (call 2) — no WAN2 switch since probe failed first
    calls = [c.args[0] for c in mock_set.call_args_list]
    assert calls[-1] == "WAN1"  # last call is restore
    assert mock_set.call_count == 2


def test_compare_wan_health_restored_false_when_restore_fails(client):
    restore_responses = [
        {"success": True},   # WAN1 switch
        {"success": True},   # WAN2 switch
        {"success": False, "error": "ER605 unreachable", "suggestion": "", "attempted": ""},  # restore
    ]
    with patch.object(ER605Client, "get_wan_policy", return_value={"success": True, "primary_wan": "WAN1"}):
        with patch.object(ER605Client, "set_wan_priority", side_effect=restore_responses):
            with patch("src.tools.wan_health._probe", side_effect=[GOOD_PROBE_WAN1, GOOD_PROBE_WAN2]):
                with patch("src.tools.wan_health.time.sleep"):
                    result = client.compare_wan_health()

    assert result["success"] is True
    assert result["restored"] is False
