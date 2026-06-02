# ER605 Phase 2 — Port Forwarding, Firewall, WAN Policy Design

**Date:** 2026-06-02
**Status:** Approved, ready for implementation planning

## Context

ER605 Phase 1 wired up two read-only tools (`get_router_info`, `get_wan_status`). Phase 2 adds write capability: port forwarding management, firewall ACL rules, and WAN failover policy — all with a `dry_run=True` gate so tools can be built and tested safely during work hours and applied live after hours.

**DHCP DNS config is out of scope.** All DHCP endpoints (`dhcpd/*`, `lan/*`, `network/dhcp`) return error 1014 on standalone ER605 firmware 2.x — they are inaccessible via the Lua CGI API. DHCP DNS is a one-time 30-second manual change via Web UI → Network → DHCP Server → Primary DNS.

## Architecture

No new files. All 8 new tools are added as methods on `ER605Client` in `src/tools/er605.py` and registered in `src/server.py` as `@mcp.tool()` functions.

The existing `_er605` singleton in `server.py` is safe to keep — `ER605Client` stores no mutable auth state (`_stok`, keys, etc.). Every method call logs in fresh via `_login()`.

Three new internal helpers are added to `ER605Client`:

```python
def _api_set(self, client, stok, resource, form, params) -> dict:
    url = f"{self._base}/cgi-bin/luci/;stok={stok}/admin/{resource}?form={form}"
    return self._post_form(client, url, {"method": "set", "params": params})

def _api_add(self, client, stok, resource, form, params) -> dict:
    url = f"{self._base}/cgi-bin/luci/;stok={stok}/admin/{resource}?form={form}"
    return self._post_form(client, url, {"method": "add", "params": params})

def _api_del(self, client, stok, resource, form, params) -> dict:
    url = f"{self._base}/cgi-bin/luci/;stok={stok}/admin/{resource}?form={form}"
    return self._post_form(client, url, {"method": "del", "params": params})
```

## ER605 API Write Pattern

All ER605 API calls are form-encoded POST with `data=json.dumps(payload)`. Reads use `{"method": "get"}`; writes use `{"method": "set"|"add"|"del", "params": {...}}`. `error_code` is a string `"0"` on success.

Endpoint paths follow the pattern: `/cgi-bin/luci/;stok={stok}/admin/{resource}?form={form}`

## Endpoint Uncertainty

The write endpoints below are speculative — they match TP-Link Lua CGI conventions but have not been probed on this firmware. The implementation plan includes a manual probe step per feature (attempt the read endpoint first). If a read endpoint returns data, writes almost certainly exist at the same path. If error 1014 is returned, the tool surfaces a structured error rather than silently failing.

## Tool Inventory

### WAN Policy

**`get_wan_policy`**
Endpoint: `GET network?form=wan_load_balance`
Returns: current mode (`"failover"` or `"load_balance"`), primary WAN, health check settings (interval, retry count, targets).

**`set_wan_priority`**
Endpoint: `SET network?form=wan_load_balance`
Params: `primary_wan: str` — `"WAN1"`, `"WAN2"`, or `"auto"` (restore automatic failover); `dry_run: bool = False`
Returns: new policy on success, or `dry_run` payload when `dry_run=True`.
Use case: WAN1 speed degrades without triggering automatic failover → force to WAN2 manually.

### Port Forwarding

**`get_port_forwards`**
Endpoint: `GET nat?form=virtual_server`
Returns: list of port forward rules with id, name, external port, internal IP, internal port, protocol, enabled state.

**`add_port_forward`**
Endpoint: `ADD nat?form=virtual_server`
Params: `name: str`, `external_port: int`, `internal_ip: str`, `internal_port: int`, `protocol: str = "tcp"` (`"tcp"`, `"udp"`, or `"both"`), `dry_run: bool = False`
Returns: created rule entry on success, or `dry_run` payload when `dry_run=True`.

**`remove_port_forward`**
Endpoint: `DEL nat?form=virtual_server`
Params: `rule_id: str`, `dry_run: bool = False`
Returns: confirmation of removal, or `dry_run` payload when `dry_run=True`.

### Firewall (ACL)

**`get_firewall_rules`**
Endpoint: `GET firewall?form=acl_ip`
Returns: list of ACL rules with id, name, source IP, destination IP, action, protocol, enabled state.

**`add_firewall_rule`**
Endpoint: `ADD firewall?form=acl_ip`
Params: `name: str`, `src_ip: str = ""` (empty = any), `dst_ip: str = ""` (empty = any), `action: str = "deny"` (`"deny"` or `"allow"`), `protocol: str = "all"` (`"tcp"`, `"udp"`, `"icmp"`, `"all"`), `dry_run: bool = False`
Returns: created rule entry on success, or `dry_run` payload when `dry_run=True`.

**`remove_firewall_rule`**
Endpoint: `DEL firewall?form=acl_ip`
Params: `rule_id: str`, `dry_run: bool = False`
Returns: confirmation of removal, or `dry_run` payload when `dry_run=True`.

## dry_run Behavior

When `dry_run=True` on any write tool:
1. Authenticate normally (full login sequence)
2. Build the request payload
3. **Do not POST to the write endpoint**
4. Return:

```python
{
    "success": True,
    "dry_run": True,
    "would_send": {
        "resource": "nat",
        "form": "virtual_server",
        "method": "add",
        "params": { ... }
    }
}
```

This allows payload verification before applying live changes.

## Error Handling

All methods return structured output:

```python
# Success
{"success": True, ...tool-specific fields...}

# Failure
{"success": False, "error": "...", "suggestion": "...", "attempted": "https://..."}
```

Error 1014 (endpoint inaccessible) surfaces:
```python
{
    "success": False,
    "error": "ER605 returned error 1014",
    "suggestion": "This endpoint may not be accessible on standalone ER605 firmware 2.x. Try the Web UI instead.",
    "attempted": "..."
}
```

Auth failures (error code 700 or non-"0" on pre-login) return the same structured error with suggestion to check credentials in `config.json`.

## Testing

Follow existing ER605 test patterns in `tests/test_er605.py` using `respx.mock` and `@respx.mock` decorator.

Each new tool gets:
- **Success path** — mock login + mock read/write endpoint returning valid data
- **Auth failure** — mock login returning error code 700
- **dry_run path** (write tools only) — verify no write POST is made, response contains `dry_run: True` and `would_send`
- **Error 1014 path** (write tools) — mock endpoint returning `{"error_code": "1014"}`, verify structured error

~24 new tests, bringing the total from 59 to ~83.

## What's Not In Scope

- DHCP DNS config — inaccessible via API (error 1014); manual Web UI change
- WAN health check threshold editing — visibility only via `get_wan_policy`
- NAT DMZ / port triggering — low value for this home network
- IPv6 firewall rules — separate concern
- Omada controller integration — ER605 is standalone
