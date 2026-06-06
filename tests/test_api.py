# tests/test_api.py
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
import src.server as server_module


def _mock_cfg():
    cfg = MagicMock()
    cfg.er605 = MagicMock(host="192.168.0.1", username="admin", password="secret")
    cfg.pihole = MagicMock(host="192.168.0.10", api_token="testtoken")
    cfg.deco = MagicMock(host="192.168.0.100", password="testpass")
    return cfg


def test_snapshot_returns_expected_keys():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.WANHealthClient") as mock_wan, \
         patch("src.api.PiholeClient") as mock_pihole, \
         patch("src.api.DecoClient") as mock_deco, \
         patch("src.api.ER605Client") as mock_er605:

        mock_wan.return_value.get_wan_health.return_value = {"success": True, "wan1": {}}
        mock_pihole.return_value.get_pihole_stats.return_value = {"success": True}
        mock_deco.return_value.get_mesh_health.return_value = {"success": True, "nodes": []}
        mock_er605.return_value.get_router_info.return_value = {"success": True}

        client = TestClient(server_module.mcp.sse_app())
        resp = client.get("/api/snapshot")

        assert resp.status_code == 200
        data = resp.json()
        assert "wan" in data
        assert "pihole" in data
        assert "mesh" in data
        assert "router" in data


def test_ping_route_success():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api._ping_host", return_value={
             "success": True, "host": "8.8.8.8",
             "avg_ms": 12.3, "packet_loss_pct": 0.0, "reachable": True,
         }):
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/diagnostics/ping", json={"host": "8.8.8.8"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["host"] == "8.8.8.8"


def test_ping_route_missing_host():
    with patch("src.server._cfg", _mock_cfg()):
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/diagnostics/ping", json={})
        assert resp.status_code == 400


def test_traceroute_route_success():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api._traceroute_host", return_value={
             "success": True, "host": "1.1.1.1",
             "hops": [{"hop": 1, "ip": "192.168.0.1", "ms": 1.2}],
         }):
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/diagnostics/traceroute", json={"host": "1.1.1.1"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


def test_speedtest_route_success():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api._run_speedtest", return_value={
             "success": True, "download_mbps": 942.1, "upload_mbps": 487.3, "ping_ms": 11.0,
         }):
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/diagnostics/speedtest")
        assert resp.status_code == 200
        assert resp.json()["download_mbps"] == 942.1


def test_dns_lookup_route_success():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api._test_dns_resolution", return_value={
             "success": True, "hostname": "example.com",
             "addresses": ["93.184.216.34"], "elapsed_ms": 8.2,
         }):
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/diagnostics/dns", json={"hostname": "example.com"})
        assert resp.status_code == 200
        assert resp.json()["addresses"] == ["93.184.216.34"]
