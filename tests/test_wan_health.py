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
