import re
import pytest
import respx
import httpx
from src.tools import er605 as er605_module
from src.tools.er605 import ER605Client, ER605Evicted, ER605Session, _rsa_encrypt

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


WAN_POLICY_URL = re.compile(
    rf"{re.escape(BASE)}/cgi-bin/luci/;stok={STOK}/admin/network\?form=wan_load_balance"
)


@respx.mock
def test_get_wan_policy_auth_failure(client):
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _login_fail_response("700")]

    result = client.get_wan_policy()

    assert result["success"] is False
    assert "authentication failed" in result["error"]


@respx.mock
def test_set_wan_priority_success(client):
    respx.post(WAN_POLICY_URL).mock(return_value=httpx.Response(200, json={
        "error_code": "0", "result": {}
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.set_wan_priority("WAN2")

    assert result["success"] is True
    assert result["primary_wan"] == "WAN2"


@respx.mock
def test_set_wan_priority_dry_run(client):
    # dry_run must NOT call the write endpoint — respx will error if it does
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.set_wan_priority("WAN2", dry_run=True)

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["would_send"]["params"]["primary_wan"] == "WAN2"
    assert result["would_send"]["method"] == "set"


def test_set_wan_priority_invalid_wan(client):
    result = client.set_wan_priority("WAN3")

    assert result["success"] is False
    assert "Invalid" in result["error"]
    assert "WAN1" in result["suggestion"]


@respx.mock
def test_set_wan_priority_error_1014(client):
    respx.post(WAN_POLICY_URL).mock(return_value=httpx.Response(200, json={
        "error_code": "1014", "result": {}
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.set_wan_priority("WAN1")

    assert result["success"] is False
    assert "1014" in result["error"]
    assert "standalone" in result["suggestion"]


PORT_FWD_URL = re.compile(
    rf"{re.escape(BASE)}/cgi-bin/luci/;stok={STOK}/admin/nat\?form=virtual_server"
)


@respx.mock
def test_get_port_forwards_auth_failure(client):
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _login_fail_response("700")]

    result = client.get_port_forwards()

    assert result["success"] is False
    assert "authentication failed" in result["error"]


@respx.mock
def test_add_port_forward_success(client):
    respx.post(PORT_FWD_URL).mock(return_value=httpx.Response(200, json={
        "error_code": "0",
        "result": {"index": "2", "name": "Game Server"},
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.add_port_forward(
        name="Game Server",
        external_port=25565,
        internal_ip="192.168.0.50",
        internal_port=25565,
        protocol="tcp",
    )

    assert result["success"] is True
    assert "rule" in result


@respx.mock
def test_add_port_forward_dry_run(client):
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.add_port_forward(
        name="Game Server",
        external_port=25565,
        internal_ip="192.168.0.50",
        internal_port=25565,
        dry_run=True,
    )

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["would_send"]["method"] == "add"
    assert result["would_send"]["params"]["name"] == "Game Server"
    assert result["would_send"]["params"]["external_port"] == 25565


def test_add_port_forward_invalid_protocol(client):
    result = client.add_port_forward(
        name="X", external_port=80, internal_ip="192.168.0.50", internal_port=80, protocol="ftp"
    )

    assert result["success"] is False
    assert "Invalid protocol" in result["error"]


@respx.mock
def test_add_port_forward_error_1014(client):
    respx.post(PORT_FWD_URL).mock(return_value=httpx.Response(200, json={
        "error_code": "1014", "result": {}
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.add_port_forward(
        name="X", external_port=80, internal_ip="192.168.0.50", internal_port=80
    )

    assert result["success"] is False
    assert "1014" in result["error"]
    assert "standalone" in result["suggestion"]


@respx.mock
def test_remove_port_forward_success(client):
    respx.post(PORT_FWD_URL).mock(return_value=httpx.Response(200, json={
        "error_code": "0", "result": {}
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.remove_port_forward("2")

    assert result["success"] is True
    assert result["removed_id"] == "2"


@respx.mock
def test_remove_port_forward_dry_run(client):
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.remove_port_forward("2", dry_run=True)

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["would_send"]["method"] == "del"
    assert result["would_send"]["params"]["index"] == "2"


@respx.mock
def test_remove_port_forward_error_1014(client):
    respx.post(PORT_FWD_URL).mock(return_value=httpx.Response(200, json={
        "error_code": "1014", "result": {}
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.remove_port_forward("2")

    assert result["success"] is False
    assert "1014" in result["error"]
    assert "standalone" in result["suggestion"]


FIREWALL_URL = re.compile(
    rf"{re.escape(BASE)}/cgi-bin/luci/;stok={STOK}/admin/firewall\?form=acl_ip"
)


@respx.mock
def test_get_firewall_rules_auth_failure(client):
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _login_fail_response("700")]

    result = client.get_firewall_rules()

    assert result["success"] is False
    assert "authentication failed" in result["error"]


@respx.mock
def test_add_firewall_rule_success(client):
    respx.post(FIREWALL_URL).mock(return_value=httpx.Response(200, json={
        "error_code": "0",
        "result": {"index": "2", "name": "Block IoT"},
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.add_firewall_rule(name="Block IoT", src_ip="192.168.0.30", action="deny")

    assert result["success"] is True
    assert "rule" in result


@respx.mock
def test_add_firewall_rule_dry_run(client):
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.add_firewall_rule(
        name="Block IoT", src_ip="192.168.0.30", action="deny", dry_run=True
    )

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["would_send"]["method"] == "add"
    assert result["would_send"]["params"]["name"] == "Block IoT"
    assert result["would_send"]["params"]["action"] == "deny"


def test_add_firewall_rule_invalid_action(client):
    result = client.add_firewall_rule(name="X", action="block")

    assert result["success"] is False
    assert "Invalid action" in result["error"]
    assert "deny" in result["suggestion"]


def test_add_firewall_rule_invalid_protocol(client):
    result = client.add_firewall_rule(name="X", protocol="ftp")

    assert result["success"] is False
    assert "Invalid protocol" in result["error"]
    assert "tcp" in result["suggestion"]


@respx.mock
def test_add_firewall_rule_error_1014(client):
    respx.post(FIREWALL_URL).mock(return_value=httpx.Response(200, json={
        "error_code": "1014", "result": {}
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.add_firewall_rule(name="X")

    assert result["success"] is False
    assert "1014" in result["error"]
    assert "standalone" in result["suggestion"]


@respx.mock
def test_remove_firewall_rule_success(client):
    respx.post(FIREWALL_URL).mock(return_value=httpx.Response(200, json={
        "error_code": "0", "result": {}
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.remove_firewall_rule("2")

    assert result["success"] is True
    assert result["removed_id"] == "2"


@respx.mock
def test_remove_firewall_rule_dry_run(client):
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.remove_firewall_rule("2", dry_run=True)

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["would_send"]["method"] == "del"
    assert result["would_send"]["params"]["index"] == "2"


@respx.mock
def test_remove_firewall_rule_error_1014(client):
    respx.post(FIREWALL_URL).mock(return_value=httpx.Response(200, json={
        "error_code": "1014", "result": {}
    }))
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]

    result = client.remove_firewall_rule("2")

    assert result["success"] is False
    assert "1014" in result["error"]
    assert "standalone" in result["suggestion"]


# --- ER605Session: one reused login for background polling ---

USAGE_URL = re.compile(rf"{re.escape(BASE)}/cgi-bin/luci/;stok=(\w+)/admin/sys_status\?form=all_usage")
USAGE_OK = {"id": 1, "result": {"cpu_usage": {"core1": 5}}, "error_code": "0"}


def _mock_logins(stoks):
    """Each login (pre-login get + login) hands out the next stok in turn."""
    issued = iter(stoks)

    def handler(request):
        if b"%22login%22" in request.content:
            return _step2_response(next(issued))
        return _step1_response()

    return respx.post(LOGIN_URL).mock(side_effect=handler)


def _mock_usage(valid_stok, stale_code):
    """sys_status answers only the current stok; any other gets `stale_code` (an int, as the router sends)."""
    def handler(request):
        stok = USAGE_URL.match(str(request.url)).group(1)
        if stok == valid_stok():
            return httpx.Response(200, json=USAGE_OK)
        return httpx.Response(200, json={"id": 1, "error_code": stale_code})

    return respx.post(USAGE_URL).mock(side_effect=handler)


@respx.mock
def test_session_reuses_one_login():
    logins = _mock_logins(["s1"])
    _mock_usage(lambda: "s1", 704)
    session = ER605Session("192.168.0.1", "admin", "secret")
    for _ in range(3):
        assert session.get("sys_status", "all_usage")["error_code"] == "0"
    # two POSTs (pre-login get + login) for a single login
    assert logins.call_count == 2


@respx.mock
def test_session_evicted_by_outside_login_raises():
    _mock_logins(["s1"])
    _mock_usage(lambda: "someone-else", 711)
    session = ER605Session("192.168.0.1", "admin", "secret")
    with pytest.raises(ER605Evicted):
        session.get("sys_status", "all_usage")


@respx.mock
def test_session_relogs_in_after_own_tool_call_login():
    current = {"stok": "s1"}
    _mock_logins(["s1", "tool", "s2"])
    _mock_usage(lambda: current["stok"], 711)
    session = ER605Session("192.168.0.1", "admin", "secret")
    session.get("sys_status", "all_usage")

    # One of this process's own tools logs in, replacing the session's stok.
    with httpx.Client(verify=False) as c:
        ER605Client("192.168.0.1", "admin", "secret")._login(c)
    current["stok"] = "s2"

    assert session.get("sys_status", "all_usage")["error_code"] == "0"


@respx.mock
def test_session_relogs_in_when_expired():
    current = {"stok": "s1"}
    _mock_logins(["s1", "s2"])
    _mock_usage(lambda: current["stok"], 704)
    session = ER605Session("192.168.0.1", "admin", "secret")
    session.get("sys_status", "all_usage")
    current["stok"] = "s2"  # router forgot s1 (timeout or reboot)
    assert session.get("sys_status", "all_usage")["error_code"] == "0"


def test_login_records_time():
    er605_module._last_login_at = 0.0
    with respx.mock:
        _mock_logins(["s1"])
        with httpx.Client(verify=False) as c:
            ER605Client("192.168.0.1", "admin", "secret")._login(c)
    assert er605_module._last_login_at > 0.0


# --- Reads on the endpoint names the router's own web UI uses (shapes captured live 2026-10-28) ---

def _admin_url(resource, form):
    return re.compile(rf"{re.escape(BASE)}/cgi-bin/luci/;stok=\w+/admin/{resource}\?form={form}$")


def _ok(result, **extra):
    return httpx.Response(200, json={"id": 1, "result": result, "error_code": "0", **extra})


def _logged_in():
    respx.post(LOGIN_URL).side_effect = [_step1_response(), _step2_response()]


@respx.mock
def test_get_wan_policy_reads_failover_and_balance(client):
    _logged_in()
    respx.post(_admin_url("balance", "line_backup")).mock(return_value=_ok([{
        "state": "on", "slave_iface": "WAN2", "master_iface": ["WAN1"], "mode": "fault_all",
        "submode": "all", "timeobj": "--",
    }], others={"max_rules": 2}))
    respx.post(_admin_url("balance", "balance_basic")).mock(
        return_value=_ok({"special_state": "on", "balance_state": "off"}))

    result = client.get_wan_policy()

    assert result == {
        "success": True, "mode": "failover", "primary_wan": "WAN1", "backup_wan": "WAN2",
        "failover_enabled": True, "failover_mode": "fault_all", "load_balance_enabled": False,
    }


@respx.mock
def test_get_wan_policy_load_balance_mode(client):
    _logged_in()
    respx.post(_admin_url("balance", "line_backup")).mock(return_value=_ok([]))
    respx.post(_admin_url("balance", "balance_basic")).mock(return_value=_ok({"balance_state": "on"}))

    result = client.get_wan_policy()

    assert result["mode"] == "load_balance"
    assert result["primary_wan"] is None


@respx.mock
def test_get_wan_policy_endpoint_error_names_endpoint(client):
    _logged_in()
    respx.post(_admin_url("balance", "line_backup")).mock(
        return_value=httpx.Response(200, json={"id": 1, "error_code": "1014"}))

    result = client.get_wan_policy()

    assert result["success"] is False
    assert "balance?form=line_backup" in result["error"] and "1014" in result["error"]


@respx.mock
def test_get_port_forwards_reads_nat_vs(client):
    _logged_in()
    respx.post(_admin_url("nat", "vs")).mock(return_value=_ok([{
        "internal_port": "88", "protocol": "UDP", "enable": "on", "external_port": "88",
        "name": "Xbox_88_UDP", "wan_ip": "", "t_label": ["WAN1", "WAN/LAN2"],
        "ipaddr": "192.168.0.148", "interface": ["WAN1", "WAN2"],
    }], others={"max_rules": 64}))

    result = client.get_port_forwards()

    assert result["success"] is True and result["count"] == 1
    assert result["rules"][0] == {
        "id": None, "name": "Xbox_88_UDP", "external_port": "88", "internal_ip": "192.168.0.148",
        "internal_port": "88", "protocol": "udp", "enabled": True, "wan_interfaces": ["WAN1", "WAN2"],
    }


@respx.mock
def test_get_port_forwards_unknown_endpoint_is_an_error(client):
    """A wrong endpoint name answers HTTP 404 with plain text, not JSON."""
    _logged_in()
    respx.post(_admin_url("nat", "vs")).mock(
        return_value=httpx.Response(404, text="No root node was registered"))

    result = client.get_port_forwards()

    assert result["success"] is False
    assert "nat?form=vs" in result["error"]
    assert result["raw"]["http_status"] == 404
    assert "No root node" in result["raw"]["body"]


@respx.mock
def test_get_firewall_rules_reads_acl_inner(client):
    _logged_in()
    respx.post(_admin_url("access_ctl", "acl_inner")).mock(return_value=_ok([{
        "iptype": "ipv4", "zone": ["LAN"], "flag": "1", "policy": "DROP", "src": "brother_printer",
        "time": "Any", "dest": "IPGROUP_LAN_REV", "v6flag": "0", "is_dst": "ipgroup", "user": "1",
        "is_src": "ipgroup", "dst_domain": {}, "service": "ALL", "name": "brother_printer",
        "states": ["new", "established", "invalid", "related"],
    }], others={"max_rules": 128}))

    result = client.get_firewall_rules()

    assert result["success"] is True and result["count"] == 1
    assert result["rules"][0] == {
        "name": "brother_printer", "action": "DROP", "source": "brother_printer",
        "source_type": "ipgroup", "destination": "IPGROUP_LAN_REV", "destination_type": "ipgroup",
        "service": "ALL", "zones": ["LAN"], "schedule": "Any", "ip_version": "ipv4",
    }


@respx.mock
def test_get_dhcp_leases_reads_clients_and_reservations(client):
    _logged_in()
    respx.post(_admin_url("dhcps", "client")).mock(return_value=_ok([
        {"leasetime": "1:49:47", "name": "--", "macaddr": "34-9F-7B-2D-D8-A8", "ipaddr": "192.168.0.154", "interface": "lan"},
        {"leasetime": "30:00:05", "name": "Xbox", "macaddr": "A0-85-FC-F8-0F-F9", "ipaddr": "192.168.0.148", "interface": "lan"},
    ]))
    respx.post(_admin_url("dhcps", "reservation")).mock(return_value=_ok([
        {"mac": "A0-85-FC-F8-0F-F9", "note": "XBOXSERIESX", "id": "1", "ip": "192.168.0.148",
         "bind": "0", "ip_bind": "on", "enable": "on", "interface": "LAN1"},
    ], others={"max_rules": 1024}))

    result = client.get_dhcp_leases()

    assert result["success"] is True
    assert result["lease_count"] == 2 and result["reservation_count"] == 1
    assert result["leases"][0] == {
        "ip": "192.168.0.154", "mac": "34:9f:7b:2d:d8:a8", "hostname": None,
        "lease_remaining": "1:49:47", "lease_remaining_seconds": 6587,
    }
    assert result["leases"][1]["hostname"] == "Xbox"
    assert result["leases"][1]["lease_remaining_seconds"] == 108005
    assert result["reservations"][0] == {
        "ip": "192.168.0.148", "mac": "a0:85:fc:f8:0f:f9", "note": "XBOXSERIESX", "enabled": True,
    }


def test_hms_to_seconds_rejects_non_durations():
    from src.tools.er605 import _hms_to_seconds
    assert _hms_to_seconds("Permanent") is None
    assert _hms_to_seconds(None) is None
    assert _hms_to_seconds("0:00:59") == 59
