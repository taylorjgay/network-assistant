import re
import pytest
import respx
import httpx
from src.tools.er605 import ER605Client, _rsa_encrypt

# Fake 1024-bit RSA modulus (256 hex chars of 'a')
MODULUS_HEX = "a" * 256
BASE = "https://192.168.0.1"
LOGIN_URL = f"{BASE}/cgi-bin/luci/;stok=/login?form=login"
STOK = "abc123"


@pytest.fixture
def client():
    return ER605Client(host="192.168.0.1", username="admin", password="secret")


def _step1_response(uptime=12345):
    return httpx.Response(200, json={
        "id": 1,
        "result": {"username": "", "password": [MODULUS_HEX, "010001"], "uptime": uptime},
        "error_code": "0",
    })


def _step2_response(stok=STOK):
    return httpx.Response(200, json={
        "id": 1,
        "result": {"stok": stok},
        "error_code": "0",
    })


def _login_fail_response(code="700"):
    return httpx.Response(200, json={"id": 1, "result": {}, "error_code": code})


@respx.mock
def test_rsa_encrypt_produces_256_hex_chars():
    ciphertext = _rsa_encrypt("secret_12345", MODULUS_HEX)
    assert len(ciphertext) == 256
    assert all(c in "0123456789abcdef" for c in ciphertext)


@respx.mock
def test_get_wan_status_success(client):
    api_pattern = re.compile(rf"{re.escape(BASE)}/cgi-bin/luci/;stok={STOK}/admin/interface\?form=status2")
    respx.post(api_pattern).mock(return_value=httpx.Response(200, json={
        "id": 1,
        "result": {
            "normal": [
                {"t_name": "WAN1", "t_isup": True, "ipaddr": "1.2.3.4", "t_proto": "dhcp",
                 "gateway": "1.2.3.1", "dns1": "8.8.8.8"},
                {"t_name": "WAN2", "t_isup": False, "ipaddr": "", "t_proto": "dhcp",
                 "gateway": "", "dns1": ""},
                {"t_name": "LAN1", "t_isup": True, "ipaddr": "192.168.0.1", "t_proto": "static",
                 "gateway": "", "dns1": ""},
            ]
        },
        "error_code": "0",
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.get_wan_status()

    assert result["success"] is True
    assert len(result["interfaces"]) == 2  # WAN1 and WAN2 only
    wan1 = result["interfaces"][0]
    assert wan1["name"] == "WAN1"
    assert wan1["up"] is True
    assert wan1["ip"] == "1.2.3.4"


@respx.mock
def test_get_wan_status_auth_failure(client):
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _login_fail_response("700")]

    result = client.get_wan_status()

    assert result["success"] is False
    assert "authentication failed" in result["error"]
    assert "700" in result["error"]


LOCALE_URL = f"{BASE}/cgi-bin/luci/;stok=/locale?form=lang"


@respx.mock
def test_get_router_info_success(client):
    fw_pattern = re.compile(rf"{re.escape(BASE)}/cgi-bin/luci/;stok={STOK}/admin/firmware\?form=upgrade")
    sys_pattern = re.compile(rf"{re.escape(BASE)}/cgi-bin/luci/;stok={STOK}/admin/sys_status\?form=all_usage")
    respx.post(fw_pattern).mock(return_value=httpx.Response(200, json={
        "id": 1,
        "result": {
            "hardware_version": "ER605 v2.0",
            "model": "ER605",
            "firmware_version": "2.3.2 Build 20251029 Rel.12727",
        },
        "error_code": "0",
    }))
    respx.post(sys_pattern).mock(return_value=httpx.Response(200, json={
        "id": 1,
        "result": {
            "cpu_usage": {"core1": 10, "core2": 14},
            "mem_usage": {"mem": 45},
        },
        "error_code": "0",
    }))
    respx.post(LOCALE_URL).mock(return_value=httpx.Response(200, json={
        "id": 1,
        "result": {"uptime": 172800, "locale": "en_US", "model": "ER605 v2.0"},
        "error_code": "0",
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.get_router_info()

    assert result["success"] is True
    assert result["model"] == "ER605 v2.0"
    assert "2.3.2" in result["firmware"]
    assert result["uptime_seconds"] == 172800
    assert result["cpu_percent"] == 12
    assert result["mem_percent"] == 45


@respx.mock
def test_get_router_info_auth_failure(client):
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _login_fail_response("700")]

    result = client.get_router_info()

    assert result["success"] is False
    assert "authentication failed" in result["error"]


@respx.mock
def test_connection_refused(client):
    respx.post(LOGIN_URL).mock(side_effect=httpx.ConnectError("refused"))

    result = client.get_wan_status()

    assert result["success"] is False
    assert "192.168.0.1" in result["attempted"]


@respx.mock
def test_uptime_used_in_password_encryption(client):
    """Verify that the uptime from the pre-login response is baked into the encrypted password."""
    captured = {}

    def capture_login(request):
        body = request.read().decode()
        captured["body"] = body
        return httpx.Response(200, json={"id": 1, "result": {"stok": STOK}, "error_code": "0"})

    respx.post(LOGIN_URL).side_effect = [_step1_response(uptime=99999), capture_login]

    api_pattern = re.compile(rf"{re.escape(BASE)}/cgi-bin/luci/;stok={STOK}/admin/interface\?form=status2")
    respx.post(api_pattern).mock(return_value=httpx.Response(200, json={
        "id": 1, "result": {"normal": []}, "error_code": "0",
    }))

    client.get_wan_status()

    expected = _rsa_encrypt("secret_99999", MODULUS_HEX)
    assert expected in captured.get("body", "")


@respx.mock
def test_api_set_sends_set_method(client):
    """_api_set must send method=set with params in the payload."""
    import json
    import urllib.parse

    captured = {}

    def capture(request):
        body = request.read().decode()
        parsed = urllib.parse.parse_qs(body)
        captured["data"] = json.loads(parsed["data"][0])
        return httpx.Response(200, json={"error_code": "0", "result": {}})

    set_url = f"{BASE}/cgi-bin/luci/;stok={STOK}/admin/network?form=test_form"
    respx.post(set_url).mock(side_effect=capture)
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    with httpx.Client(verify=False) as c:
        stok, _ = client._login(c)
        client._api_set(c, stok, "network", "test_form", {"key": "val"})

    assert captured["data"]["method"] == "set"
    assert captured["data"]["params"] == {"key": "val"}
