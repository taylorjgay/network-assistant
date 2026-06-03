from unittest.mock import MagicMock, patch
import pytest

from src.tools.upnp import get_upnp_status, get_upnp_portmaps


def _make_upnp(ext_ip="1.2.3.4", lan="192.168.0.10", status=("Connected", 0, "ERROR_NONE"),
               conn_type="IP_Routed"):
    u = MagicMock()
    u.lanaddr = lan
    u.externalipaddress.return_value = ext_ip
    u.statusinfo.return_value = status
    u.connectiontype.return_value = conn_type
    return u


# ---------------------------------------------------------------------------
# get_upnp_status
# ---------------------------------------------------------------------------

class TestGetUpnpStatus:
    def test_no_gateway(self):
        with patch("src.tools.upnp._discover", return_value=None):
            result = get_upnp_status()
        assert result["success"] is True
        assert result["available"] is False

    def test_gateway_found(self):
        u = _make_upnp()
        with patch("src.tools.upnp._discover", return_value=u):
            result = get_upnp_status()
        assert result["success"] is True
        assert result["available"] is True
        assert result["external_ip"] == "1.2.3.4"
        assert result["lan_ip"] == "192.168.0.10"
        assert result["status"] == "Connected"
        assert result["connection_type"] == "IP_Routed"

    def test_exception_returns_error(self):
        with patch("src.tools.upnp._discover", side_effect=Exception("boom")):
            result = get_upnp_status()
        assert result["success"] is False
        assert "boom" in result["error"]

    def test_empty_status_tuple(self):
        u = _make_upnp(status=())
        with patch("src.tools.upnp._discover", return_value=u):
            result = get_upnp_status()
        assert result["status"] == "Unknown"

    def test_private_external_ip(self):
        # ER605 is behind Nokia modem — external IP may be private
        u = _make_upnp(ext_ip="192.168.1.70")
        with patch("src.tools.upnp._discover", return_value=u):
            result = get_upnp_status()
        assert result["external_ip"] == "192.168.1.70"


# ---------------------------------------------------------------------------
# get_upnp_portmaps
# ---------------------------------------------------------------------------

def _portmap_side_effect(entries):
    """Return a side_effect function that yields entries then None."""
    calls = iter(entries + [None])
    return lambda i: next(calls)


class TestGetUpnpPortmaps:
    def test_no_gateway(self):
        with patch("src.tools.upnp._discover", return_value=None):
            result = get_upnp_portmaps()
        assert result["success"] is True
        assert result["available"] is False
        assert result["mappings"] == []

    def test_no_mappings(self):
        u = _make_upnp()
        u.getgenericportmapping.return_value = None
        with patch("src.tools.upnp._discover", return_value=u):
            result = get_upnp_portmaps()
        assert result["success"] is True
        assert result["available"] is True
        assert result["count"] == 0
        assert result["mappings"] == []

    def test_single_mapping(self):
        u = _make_upnp()
        entry = (3074, "UDP", ("192.168.0.50", 3074), "Xbox", 1, "", 0)
        u.getgenericportmapping.side_effect = _portmap_side_effect([entry])
        with patch("src.tools.upnp._discover", return_value=u):
            result = get_upnp_portmaps()
        assert result["count"] == 1
        m = result["mappings"][0]
        assert m["external_port"] == 3074
        assert m["protocol"] == "UDP"
        assert m["internal_host"] == "192.168.0.50"
        assert m["internal_port"] == 3074
        assert m["description"] == "Xbox"
        assert m["enabled"] is True
        assert m["remote_host"] == "any"
        assert m["lease_seconds"] == 0

    def test_multiple_mappings(self):
        u = _make_upnp()
        entries = [
            (3074, "UDP", ("192.168.0.50", 3074), "Xbox", 1, "", 0),
            (3075, "TCP", ("192.168.0.51", 3075), "Switch", 1, "", 3600),
            (51820, "UDP", ("192.168.0.10", 51820), "WireGuard", 1, "", 0),
        ]
        u.getgenericportmapping.side_effect = _portmap_side_effect(entries)
        with patch("src.tools.upnp._discover", return_value=u):
            result = get_upnp_portmaps()
        assert result["count"] == 3
        assert result["mappings"][1]["description"] == "Switch"
        assert result["mappings"][2]["external_port"] == 51820

    def test_remote_host_empty_string_becomes_any(self):
        u = _make_upnp()
        entry = (80, "TCP", ("192.168.0.5", 80), "server", 1, "", 0)
        u.getgenericportmapping.side_effect = _portmap_side_effect([entry])
        with patch("src.tools.upnp._discover", return_value=u):
            result = get_upnp_portmaps()
        assert result["mappings"][0]["remote_host"] == "any"

    def test_remote_host_set(self):
        u = _make_upnp()
        entry = (443, "TCP", ("192.168.0.5", 443), "server", 1, "203.0.113.5", 0)
        u.getgenericportmapping.side_effect = _portmap_side_effect([entry])
        with patch("src.tools.upnp._discover", return_value=u):
            result = get_upnp_portmaps()
        assert result["mappings"][0]["remote_host"] == "203.0.113.5"

    def test_disabled_mapping(self):
        u = _make_upnp()
        entry = (8080, "TCP", ("192.168.0.20", 8080), "test", 0, "", 0)
        u.getgenericportmapping.side_effect = _portmap_side_effect([entry])
        with patch("src.tools.upnp._discover", return_value=u):
            result = get_upnp_portmaps()
        assert result["mappings"][0]["enabled"] is False

    def test_exception_returns_error(self):
        with patch("src.tools.upnp._discover", side_effect=Exception("timeout")):
            result = get_upnp_portmaps()
        assert result["success"] is False
        assert "timeout" in result["error"]
