# Pi-hole Phase 2 — Full API Coverage Design

**Date:** 2026-06-02  
**Status:** Approved, ready for implementation planning

## Context

Pi-hole v6.4.2 is live on `192.168.0.200`. Phase 1 wired up `get_pihole_stats` (read-only summary). Phase 2 adds full MCP coverage of the Pi-hole v6 API: query log, domain management, blocking control, gravity updates, client info, and system status.

**Motivation:** User is about to point ER605 DHCP DNS at Pi-hole. Needs visibility into what's being blocked and the ability to whitelist domains conversationally without logging into the Pi-hole web UI.

## Architecture

No new files or architectural patterns. All new tools:
- Live in `src/tools/pihole.py` as new methods on `PiholeClient`
- Are registered in `src/server.py` as `@mcp.tool()` functions
- Follow Phase 1 structured error pattern: `{success, error, suggestion, attempted}` on failure
- Use `_get_sid()` for auth and `X-FTL-SID` header for all requests

**Bug fix included:** `server.py` currently has a singleton `_pihole` instance. Each tool call must create a fresh `PiholeClient` (same fix already applied to `DecoClient` in Phase 1).

## Pi-hole v6 Auth

- `POST /api/auth` with `{"password": "..."}` → returns `session.sid`
- All authenticated requests use `X-FTL-SID: <sid>` header (NOT query param or cookie)
- Password stored in `config.json` as `api_token` (value is the `cli_pw` app password)

## Tool Inventory

### Existing (unchanged)
- **`get_pihole_stats`** — summary stats + blocking enabled state

### New Read Tools

**`get_query_log`**  
Endpoint: `GET /api/queries`  
Params: `blocked` (bool, optional — filter to blocked only), `domain` (string, optional), `client` (string, optional), `limit` (int, default 50)  
Returns: list of recent queries with domain, client, status (blocked/allowed/cached/forwarded), timestamp, response type

**`get_top_domains`**  
Endpoint: `GET /api/stats/top_domains`  
Params: `blocked` (bool, default false — true for top blocked), `count` (int, default 10)  
Returns: ranked list of domains with query count

**`get_top_clients`**  
Endpoint: `GET /api/stats/top_clients`  
Params: `count` (int, default 10)  
Returns: ranked list of clients (IP/hostname) with query count

**`get_domain_lists`**  
Endpoint: `GET /api/domains`  
Params: none  
Returns: all entries across allowlist and blocklist, grouped by type (allow/block) and kind (exact/regex), with enabled state and comment

**`get_clients`**  
Endpoint: `GET /api/clients`  
Params: none  
Returns: all known clients with IP, hostname (if known), query count, last-seen timestamp

**`get_pihole_system`**  
Endpoint: `GET /api/info/system`  
Params: none  
Returns: CPU usage, memory usage, temperature (if available), uptime, hostname

### New Write Tools

**`add_domain`**  
Endpoint: `POST /api/domains`  
Params: `domain` (string, required), `list_type` (`"allow"` or `"block"`, required), `kind` (`"exact"` or `"regex"`, default `"exact"`), `comment` (string, optional)  
Returns: confirmation with the created entry

**`remove_domain`**  
Endpoint: `DELETE /api/domains/{type}/{kind}/{domain}`  
Params: `domain` (string, required), `list_type` (`"allow"` or `"block"`, required), `kind` (`"exact"` or `"regex"`, default `"exact"`)  
Returns: confirmation of removal

**`set_blocking`**  
Endpoint: `POST /api/dns/blocking`  
Params: `enabled` (bool, required), `timer` (int seconds, optional — auto re-enables blocking after N seconds)  
Returns: new blocking state and timer if set. Typical use: `set_blocking(enabled=False, timer=300)` to pause for 5 minutes.

**`update_gravity`**  
Endpoint: `POST /api/gravity`  
Params: none  
Returns: confirmation that gravity update was triggered (runs async on Pi; does not wait for completion)

## Error Handling

All methods return structured output:
```python
# Success
{"success": True, ...tool-specific fields...}

# Failure  
{"success": False, "error": "...", "suggestion": "...", "attempted": "http://..."}
```

Auth failures (bad SID, expired session) surface as HTTP 401 → caught and returned as structured error with suggestion to check `api_token` in `config.json`.

Some endpoints (gravity update, domain add/remove) may not exist at exactly these paths — the implementation plan includes a probe step per tool before writing the method.

## Testing

Follow Phase 1 pattern: mock `httpx.Client` at the method level. Each new `PiholeClient` method gets a unit test covering the success path and at least one error path (connection error or HTTP error). Write operations additionally test the structured error output on 4xx responses.

Existing 34 tests must continue to pass after the singleton fix in `server.py`.

## What's Not In Scope

- Adlist/group management (add/remove upstream blocklist sources) — complex, low conversational value
- TOTP / multi-factor auth — not configured on this Pi-hole
- ER605 write tools — separate future spec
