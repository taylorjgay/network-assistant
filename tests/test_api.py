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
