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


@respx.mock
def test_get_top_domains_allowed(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/stats/top_domains").mock(
        return_value=httpx.Response(200, json={
            "domains": {"google.com": 500, "apple.com": 300},
            "total_queries": 1000,
        })
    )
    result = client.get_top_domains(blocked=False, count=10)
    assert result["success"] is True
    assert len(result["domains"]) == 2
    assert result["domains"][0]["domain"] == "google.com"
    assert result["domains"][0]["count"] == 500
    assert result["blocked_filter"] is False


@respx.mock
def test_get_top_domains_blocked(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/stats/top_domains").mock(
        return_value=httpx.Response(200, json={
            "domains": {"ads.evil.com": 120},
            "total_queries": 1000,
        })
    )
    result = client.get_top_domains(blocked=True)
    assert result["success"] is True
    assert result["domains"][0]["domain"] == "ads.evil.com"
    assert result["blocked_filter"] is True


@respx.mock
def test_get_top_clients(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/stats/top_clients").mock(
        return_value=httpx.Response(200, json={
            "clients": {"192.168.0.50|mypc": 800, "192.168.0.51|phone": 400},
            "total_queries": 1200,
        })
    )
    result = client.get_top_clients(count=10)
    assert result["success"] is True
    assert len(result["clients"]) == 2
    assert result["clients"][0]["ip"] == "192.168.0.50"
    assert result["clients"][0]["name"] == "mypc"
    assert result["clients"][0]["count"] == 800


@respx.mock
def test_get_top_clients_connect_error(client):
    respx.post("http://192.168.0.10/api/auth").mock(
        side_effect=httpx.ConnectError("refused")
    )
    result = client.get_top_clients()
    assert result["success"] is False
    assert "suggestion" in result


@respx.mock
def test_get_domain_lists(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/domains").mock(
        return_value=httpx.Response(200, json={"domains": [
            {"id": 1, "type": 0, "kind": 0, "domain": "safe.com", "enabled": True, "comment": ""},
            {"id": 2, "type": 1, "kind": 0, "domain": "ads.evil.com", "enabled": True, "comment": "spam"},
            {"id": 3, "type": 1, "kind": 1, "domain": r"^tracker\.", "enabled": False, "comment": ""},
        ]})
    )
    result = client.get_domain_lists()
    assert result["success"] is True
    assert len(result["allow"]) == 1
    assert result["allow"][0]["domain"] == "safe.com"
    assert len(result["block"]) == 2
    assert result["block"][0]["kind"] == "exact"
    assert result["block"][1]["kind"] == "regex"
    assert result["block"][1]["enabled"] is False


@respx.mock
def test_get_domain_lists_empty(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/domains").mock(
        return_value=httpx.Response(200, json={"domains": []})
    )
    result = client.get_domain_lists()
    assert result["success"] is True
    assert result["allow"] == []
    assert result["block"] == []


@respx.mock
def test_get_clients(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/clients").mock(
        return_value=httpx.Response(200, json={"clients": [
            {"ip": "192.168.0.50", "name": "mypc", "count": 800, "last_query": 1717300000},
            {"ip": "192.168.0.51", "name": "", "count": 200, "last_query": 1717290000},
        ]})
    )
    result = client.get_clients()
    assert result["success"] is True
    assert len(result["clients"]) == 2
    assert result["clients"][0]["ip"] == "192.168.0.50"
    assert result["clients"][0]["hostname"] == "mypc"
    assert result["clients"][0]["query_count"] == 800


@respx.mock
def test_get_clients_connect_error(client):
    respx.post("http://192.168.0.10/api/auth").mock(
        side_effect=httpx.ConnectError("refused")
    )
    result = client.get_clients()
    assert result["success"] is False
    assert "suggestion" in result
