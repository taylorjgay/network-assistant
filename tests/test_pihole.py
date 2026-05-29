import pytest
import respx
import httpx
from src.tools.pihole import PiholeClient


@pytest.fixture
def client():
    return PiholeClient(host="192.168.0.10", api_token="testtoken")


@respx.mock
def test_get_stats_v5(client):
    respx.get("http://192.168.0.10/admin/api.php").mock(return_value=httpx.Response(200, json={
        "dns_queries_today": 1234,
        "ads_blocked_today": 100,
        "ads_percentage_today": 8.1,
        "domains_being_blocked": 95000,
        "status": "enabled",
    }))
    result = client.get_pihole_stats()
    assert result["success"] is True
    assert result["queries_today"] == 1234
    assert result["blocked_today"] == 100
    assert result["block_pct"] == 8.1
    assert result["enabled"] is True


@respx.mock
def test_get_stats_http_error(client):
    respx.get("http://192.168.0.10/admin/api.php").mock(return_value=httpx.Response(500))
    result = client.get_pihole_stats()
    assert result["success"] is False
    assert "suggestion" in result


@respx.mock
def test_test_dns_via_pihole(client):
    respx.get("http://192.168.0.10/admin/api.php").mock(return_value=httpx.Response(200, json={
        "FTLnotrunning": False,
        "status": "enabled",
    }))
    result = client.get_pihole_stats()
    assert result["success"] is True


@respx.mock
def test_connection_refused(client):
    respx.get("http://192.168.0.10/admin/api.php").mock(side_effect=httpx.ConnectError("refused"))
    result = client.get_pihole_stats()
    assert result["success"] is False
    assert "192.168.0.10" in result["attempted"]
