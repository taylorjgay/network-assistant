# tests/test_api.py
import asyncio
import time
from unittest.mock import patch, MagicMock

import pytest
from starlette.testclient import TestClient

import src.api as api_module
import src.server as server_module
from src.tools.er605 import ER605Evicted


def _mock_cfg():
    cfg = MagicMock()
    cfg.er605 = MagicMock(host="192.168.0.1", username="admin", password="secret")
    cfg.pihole = MagicMock(host="192.168.0.10", api_token="testtoken")
    cfg.deco = MagicMock(host="192.168.0.100", password="testpass")
    return cfg


def test_snapshot_returns_expected_keys():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api._poll_er605", return_value=({"success": True, "wan1": {}}, {"success": True})), \
         patch("src.api.PiholeClient") as mock_pihole, \
         patch("src.api.DecoClient") as mock_deco:

        mock_pihole.return_value.get_pihole_stats.return_value = {"success": True}
        mock_deco.return_value.get_mesh_health.return_value = {"success": True, "nodes": []}

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


def test_wan_speed_compare_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.WANSpeedClient") as mock_speed:
        mock_speed.return_value.compare_wan_speed.return_value = {
            "success": True, "quick": True,
            "wan1": {"latency_ms": 12.0, "packet_loss_pct": 0.0},
            "wan2": {"latency_ms": 28.0, "packet_loss_pct": 0.0},
            "recommendation": "WAN1 recommended — 2.3× lower latency",
            "restored": True,
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/wan/speed/compare", json={"quick": True})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["recommendation"] == "WAN1 recommended — 2.3× lower latency"


def test_pihole_gravity_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.update_gravity.return_value = {
            "success": True, "message": "Gravity update triggered — runs in background on Pi-hole",
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/pihole/gravity")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


def test_pihole_top_clients_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.get_top_clients.return_value = {
            "success": True,
            "clients": [{"ip": "192.168.0.50", "name": "laptop", "count": 1234}],
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.get("/api/pihole/top-clients")
        assert resp.status_code == 200
        assert resp.json()["clients"][0]["ip"] == "192.168.0.50"


def test_pihole_clients_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.get_clients.return_value = {
            "success": True,
            "clients": [{"ip": "192.168.0.50", "hostname": "laptop", "query_count": 5000, "last_query": 1700000000}],
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.get("/api/pihole/clients")
        assert resp.status_code == 200
        assert len(resp.json()["clients"]) == 1


def test_pihole_domains_get_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.get_domain_lists.return_value = {
            "success": True,
            "allow": [{"domain": "t.co", "kind": "exact", "enabled": True, "comment": ""}],
            "block": [],
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.get("/api/pihole/domains")
        assert resp.status_code == 200
        assert resp.json()["allow"][0]["domain"] == "t.co"


def test_pihole_domains_post_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.add_domain.return_value = {
            "success": True, "domain": "ads.example.com", "list_type": "block", "kind": "exact",
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/pihole/domains", json={
            "domain": "ads.example.com", "list_type": "block", "kind": "exact",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True


def test_pihole_domains_delete_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.remove_domain.return_value = {
            "success": True, "domain": "ads.example.com", "list_type": "block", "kind": "exact",
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.delete("/api/pihole/domains/block/exact/ads.example.com")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# --- ER605 polling: back off when someone else logs in; warmer stops when idle ---

@pytest.fixture
def fresh_er605_state(monkeypatch):
    monkeypatch.setattr(api_module, "_er605_session", None)
    monkeypatch.setattr(api_module, "_er605_paused_until", 0.0)
    monkeypatch.setattr(api_module, "_er605_last", None)


def test_poll_er605_pauses_and_serves_last_data_when_evicted(fresh_er605_state, monkeypatch):
    last_wan, last_router = {"success": True, "active_wan": "WAN1"}, {"success": True, "model": "ER605 v2.0"}
    monkeypatch.setattr(api_module, "_er605_last", (last_wan, last_router))
    with patch("src.api.ER605Session") as mock_session:
        mock_session.return_value.get.side_effect = ER605Evicted()
        wan, router = api_module._poll_er605(_mock_cfg())
        assert wan["paused"] is True and router["paused"] is True
        assert wan["active_wan"] == "WAN1" and router["model"] == "ER605 v2.0"
        assert router["paused_seconds_left"] == api_module._ER605_PAUSE

        # While paused, the router is not touched at all.
        api_module._poll_er605(_mock_cfg())
        assert mock_session.return_value.get.call_count == 1


def test_poll_er605_evicted_with_no_previous_data(fresh_er605_state):
    with patch("src.api.ER605Session") as mock_session:
        mock_session.return_value.get.side_effect = ER605Evicted()
        wan, router = api_module._poll_er605(_mock_cfg())
    assert router["success"] is False and router["paused"] is True
    assert "web UI" in router["error"]


def test_poll_er605_resumes_after_pause(fresh_er605_state, monkeypatch):
    monkeypatch.setattr(api_module, "_er605_paused_until", time.monotonic() - 1)
    with patch("src.api.ER605Session") as mock_session, \
         patch("src.api.health_from_wan_status", return_value={"success": True, "active_wan": "WAN1"}):
        mock_session.return_value.get.side_effect = [
            {"error_code": "0", "result": {"normal": []}},
            {"error_code": "0", "result": {"hardware_version": "ER605 v2.0"}},
            {"error_code": "0", "result": {}},
        ]
        mock_session.return_value.uptime.return_value = 100
        wan, router = api_module._poll_er605(_mock_cfg())
    assert "paused" not in router and router["model"] == "ER605 v2.0"
    assert api_module._er605_last == (wan, router)


def test_warmer_stops_when_dashboard_idle(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:  # dashboard closed after the first refresh
            monkeypatch.setattr(api_module, "_last_snapshot_request", time.monotonic() - 10_000)

    monkeypatch.setattr(api_module, "_last_snapshot_request", time.monotonic())
    monkeypatch.setattr(api_module.asyncio, "sleep", fake_sleep)
    with patch("src.api._do_snapshot", return_value={"wan": {}}) as mock_snapshot:
        asyncio.run(api_module.warm_snapshot_loop(_mock_cfg()))
    assert mock_snapshot.call_count == 1
    assert len(sleeps) == 2


# --- Snapshot cache: serve whatever exists at once, flag it stale, refresh behind it ---

@pytest.fixture
def snapshot_state(monkeypatch):
    monkeypatch.setattr(api_module, "_snapshot_cache", None)
    monkeypatch.setattr(api_module, "_snapshot_ts", 0.0)
    monkeypatch.setattr(api_module, "_refresh_task", None)
    clients_refresh = MagicMock()
    monkeypatch.setattr(api_module, "_refresh_deco_clients", clients_refresh)
    return clients_refresh


def test_snapshot_serves_weeks_old_cache_immediately_and_refreshes(snapshot_state, monkeypatch):
    three_weeks = 21 * 86400
    monkeypatch.setattr(api_module, "_snapshot_cache", {"wan": {"old": True}})
    monkeypatch.setattr(api_module, "_snapshot_ts", time.monotonic() - three_weeks)

    async def run():
        with patch("src.api._do_snapshot", return_value={"wan": {"old": False}}) as mock_snapshot:
            served = await api_module.snapshot(_mock_cfg())
            await api_module._refresh_task
            return served, mock_snapshot.call_count

    served, calls = asyncio.run(run())
    assert served["wan"] == {"old": True}
    assert served["stale"] is True and served["age_seconds"] >= three_weeks
    assert calls == 1
    snapshot_state.assert_not_called()  # the ~25s client refresh waits for fresh data
    assert api_module._snapshot_cache == {"wan": {"old": False}}


def test_snapshot_fresh_cache_is_not_stale_and_not_refreshed(snapshot_state, monkeypatch):
    monkeypatch.setattr(api_module, "_snapshot_cache", {"wan": {}})
    monkeypatch.setattr(api_module, "_snapshot_ts", time.monotonic() - 5)

    async def run():
        with patch("src.api._do_snapshot") as mock_snapshot:
            served = await api_module.snapshot(_mock_cfg())
            return served, mock_snapshot.call_count

    served, calls = asyncio.run(run())
    assert served["stale"] is False and calls == 0
    assert api_module._refresh_task is None
    snapshot_state.assert_called_once()


def test_snapshot_without_cache_waits_for_a_real_one(snapshot_state):
    async def run():
        with patch("src.api._do_snapshot", return_value={"wan": {"live": True}}):
            return await api_module.snapshot(_mock_cfg())

    served = asyncio.run(run())
    assert served["wan"] == {"live": True}
    assert served["stale"] is False and served["age_seconds"] == 0


def test_deco_clients_refresh_runs_at_most_every_five_minutes(monkeypatch):
    monkeypatch.setattr(api_module, "_deco_clients_started", float("-inf"))
    monkeypatch.setattr(api_module, "_deco_clients_task", None)

    async def run():
        with patch("src.api.DecoClient") as mock_deco:
            mock_deco.return_value.get_connected_clients.return_value = {"success": True, "clients": []}
            api_module._refresh_deco_clients(_mock_cfg())
            await api_module._deco_clients_task
            api_module._refresh_deco_clients(_mock_cfg())  # too soon: ignored
            return mock_deco.return_value.get_connected_clients.call_count

    assert asyncio.run(run()) == 1
