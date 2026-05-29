import hashlib
import re
import pytest
import respx
import httpx
from src.tools.er605 import ER605Client


@pytest.fixture
def client():
    return ER605Client(host="192.168.0.1", username="admin", password="secret")


def md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest().upper()


@respx.mock
def test_get_wan_status_success(client):
    # More specific pattern first (stok endpoint), then login endpoint
    respx.post(re.compile(r"http://192\.168\.0\.1/stok=.*")).mock(return_value=httpx.Response(200, json={
        "error_code": 0,
        "network": {
            "wan_status": {
                "link_status": "up",
                "ip": "1.2.3.4",
                "proto": "dhcp",
                "uptime": 86400,
            }
        }
    }))
    respx.post("http://192.168.0.1/").mock(return_value=httpx.Response(200, json={
        "error_code": 0,
        "login": {"stok": "abc123"}
    }))
    result = client.get_wan_status()
    assert result["success"] is True
    assert result["wan1"]["link_status"] == "up"
    assert result["wan1"]["ip"] == "1.2.3.4"


@respx.mock
def test_get_wan_status_auth_failure(client):
    respx.post("http://192.168.0.1/").mock(return_value=httpx.Response(200, json={
        "error_code": -22001,
        "error_msg": "invalid username or password"
    }))
    result = client.get_wan_status()
    assert result["success"] is False
    assert "auth" in result["error"].lower() or "password" in result["suggestion"].lower()


@respx.mock
def test_get_router_info_success(client):
    # More specific pattern first (stok endpoint), then login endpoint
    respx.post(re.compile(r"http://192\.168\.0\.1/stok=.*")).mock(return_value=httpx.Response(200, json={
        "error_code": 0,
        "system": {
            "name": {
                "model": "TL-ER605",
                "firmware": "2.0.0 Build 20221208",
                "uptime": 172800,
            }
        }
    }))
    respx.post("http://192.168.0.1/").mock(return_value=httpx.Response(200, json={
        "error_code": 0,
        "login": {"stok": "abc123"}
    }))
    result = client.get_router_info()
    assert result["success"] is True
    assert result["model"] == "TL-ER605"
    assert "firmware" in result


@respx.mock
def test_connection_refused(client):
    respx.post("http://192.168.0.1/").mock(side_effect=httpx.ConnectError("refused"))
    result = client.get_wan_status()
    assert result["success"] is False
    assert "192.168.0.1" in result["attempted"]
