import pytest
import respx
import httpx
from src.tools.pihole import PiholeClient


@pytest.fixture
def client():
    return PiholeClient(host="192.168.0.10", api_token="testtoken")


def _mock_auth():
    respx.post("http://192.168.0.10/api/auth").mock(
        return_value=httpx.Response(200, json={"session": {"valid": True, "sid": "test-sid"}})
    )


@respx.mock
def test_get_stats_success(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/stats/summary").mock(
        return_value=httpx.Response(200, json={
            "queries": {"total": 1234, "blocked": 100, "percent_blocked": 8.1},
            "gravity": {"domains_being_blocked": 95000},
        })
    )
    respx.get("http://192.168.0.10/api/dns/blocking").mock(
        return_value=httpx.Response(200, json={"blocking": "enabled"})
    )
    result = client.get_pihole_stats()
    assert result["success"] is True
    assert result["queries_today"] == 1234
    assert result["blocked_today"] == 100
    assert result["block_pct"] == 8.1
    assert result["domains_blocked"] == 95000
    assert result["enabled"] is True


@respx.mock
def test_get_stats_disabled(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/stats/summary").mock(
        return_value=httpx.Response(200, json={
            "queries": {"total": 500, "blocked": 0, "percent_blocked": 0.0},
            "gravity": {"domains_being_blocked": 95000},
        })
    )
    respx.get("http://192.168.0.10/api/dns/blocking").mock(
        return_value=httpx.Response(200, json={"blocking": "disabled"})
    )
    result = client.get_pihole_stats()
    assert result["success"] is True
    assert result["enabled"] is False


@respx.mock
def test_get_stats_auth_failure(client):
    respx.post("http://192.168.0.10/api/auth").mock(
        return_value=httpx.Response(200, json={"session": {"valid": False}})
    )
    result = client.get_pihole_stats()
    assert result["success"] is False
    assert "Authentication" in result["error"]
    assert "api_token" in result["suggestion"]


@respx.mock
def test_get_stats_http_error(client):
    respx.post("http://192.168.0.10/api/auth").mock(
        return_value=httpx.Response(401)
    )
    result = client.get_pihole_stats()
    assert result["success"] is False
    assert "suggestion" in result


@respx.mock
def test_get_stats_connect_error(client):
    respx.post("http://192.168.0.10/api/auth").mock(
        side_effect=httpx.ConnectError("refused")
    )
    result = client.get_pihole_stats()
    assert result["success"] is False
    assert "192.168.0.10" in result["attempted"]


@respx.mock
def test_test_dns_resolution_not_blocked(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/queries").mock(
        return_value=httpx.Response(200, json={"queries": [
            {"domain": "google.com", "status": 2},
            {"domain": "google.com", "status": 3},
        ]})
    )
    result = client.test_dns_resolution("google.com")
    assert result["success"] is True
    assert result["hostname"] == "google.com"
    assert result["recent_queries"] == 2
    assert result["recent_blocked"] == 0
    assert result["is_recently_blocked"] is False


@respx.mock
def test_test_dns_resolution_is_blocked(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/queries").mock(
        return_value=httpx.Response(200, json={"queries": [
            {"domain": "ads.example.com", "status": 1},
        ]})
    )
    result = client.test_dns_resolution("ads.example.com")
    assert result["success"] is True
    assert result["is_recently_blocked"] is True
    assert result["recent_blocked"] == 1


@respx.mock
def test_test_dns_resolution_auth_failure(client):
    respx.post("http://192.168.0.10/api/auth").mock(
        return_value=httpx.Response(200, json={"session": {"valid": False}})
    )
    result = client.test_dns_resolution("google.com")
    assert result["success"] is False
    assert result["hostname"] == "google.com"
    assert "Authentication" in result["error"]


@respx.mock
def test_get_query_log_default(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/queries").mock(
        return_value=httpx.Response(200, json={"queries": [
            {"id": 1, "time": 1717300000.0, "type": "A", "domain": "example.com",
             "client": {"ip": "192.168.0.50", "name": "mypc"}, "status": 2,
             "reply": {"type": "IP", "time": 1.2}},
            {"id": 2, "time": 1717300010.0, "type": "A", "domain": "ads.bad.com",
             "client": {"ip": "192.168.0.51", "name": "phone"}, "status": 1,
             "reply": {"type": "NXDOMAIN", "time": 0.0}},
        ]})
    )
    result = client.get_query_log()
    assert result["success"] is True
    assert len(result["queries"]) == 2
    assert result["queries"][0]["domain"] == "example.com"
    assert result["queries"][0]["status"] == "forwarded"
    assert result["queries"][1]["status"] == "blocked"
    assert result["queries"][1]["client"] == "192.168.0.51"


@respx.mock
def test_get_query_log_blocked_filter(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/queries").mock(
        return_value=httpx.Response(200, json={"queries": [
            {"id": 3, "time": 1717300020.0, "type": "A", "domain": "tracker.com",
             "client": {"ip": "192.168.0.50", "name": ""}, "status": 1,
             "reply": {"type": "NXDOMAIN", "time": 0.0}},
        ]})
    )
    result = client.get_query_log(blocked=True)
    assert result["success"] is True
    assert len(result["queries"]) == 1


@respx.mock
def test_get_query_log_connect_error(client):
    respx.post("http://192.168.0.10/api/auth").mock(
        side_effect=httpx.ConnectError("refused")
    )
    result = client.get_query_log()
    assert result["success"] is False
    assert "suggestion" in result
