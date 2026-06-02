# Pi-hole Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 9 new MCP tools for full Pi-hole v6 API coverage: query log, top domains/clients, domain list management, blocking control, gravity update, client info, and system status.

**Architecture:** All new methods live on `PiholeClient` in `src/tools/pihole.py`; each is registered as an `@mcp.tool()` in `src/server.py`. The singleton `_pihole` instance in `server.py` is removed — each tool call creates a fresh `PiholeClient`. Every method authenticates via `POST /api/auth → X-FTL-SID header` using the shared `_get_sid()` helper.

**Tech Stack:** Python 3.11, httpx, respx (test mocking), FastMCP

---

## File Map

- **Modify:** `src/tools/pihole.py` — add 9 new methods to `PiholeClient`
- **Modify:** `src/server.py` — remove `_pihole` singleton; add 9 new `@mcp.tool()` functions; create fresh `PiholeClient` per tool call
- **Modify:** `tests/test_pihole.py` — rewrite existing v5 tests to v6 mocking pattern; add tests for all 9 new methods
- **Modify:** `tests/test_server.py` — add 9 new tool names to `EXPECTED_TOOLS`

---

### Task 1: Fix singleton bug + rewrite existing pihole tests for v6

The existing `tests/test_pihole.py` mocks `/admin/api.php` (v5 API). The implementation already uses v6 (`/api/auth`, `/api/stats/summary`). This mismatch means the tests pass vacuously (wrong URL never fires). This task aligns tests with the real implementation.

**Files:**
- Modify: `src/server.py:23`
- Modify: `tests/test_pihole.py`

- [ ] **Step 1: Fix the singleton in server.py**

Replace lines 21–23 in `src/server.py`:

```python
# OLD:
_er605 = ER605Client(**vars(_cfg.er605)) if _cfg else None
_deco = DecoClient(**vars(_cfg.deco)) if _cfg else None
_pihole = PiholeClient(**vars(_cfg.pihole)) if _cfg else None
```

```python
# NEW (remove _pihole singleton; _er605 stays as singleton since it has no concurrency issue in Phase 1):
_er605 = ER605Client(**vars(_cfg.er605)) if _cfg else None
_deco = DecoClient(**vars(_cfg.deco)) if _cfg else None
```

Then replace the `get_pihole_stats` tool in `src/server.py`:

```python
@mcp.tool()
def get_pihole_stats() -> dict:
    """Get Pi-hole query stats: total queries, blocked count, block percentage, enabled state."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_pihole_stats()
```

- [ ] **Step 2: Rewrite tests/test_pihole.py for v6**

Replace the entire file:

```python
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
```

Note: Pi-hole v6 status codes — blocked statuses are 1 (gravity), 4 (regex block), 5 (exact block), 6 (external block). The existing `test_dns_resolution` method checks `q.get("status", "").startswith("block")` — this won't match integer status codes. Fix that method too.

- [ ] **Step 3: Fix test_dns_resolution status check in pihole.py**

In `src/tools/pihole.py`, replace the blocked query filter in `test_dns_resolution`:

```python
# OLD:
blocked = [q for q in queries if q.get("status", "").startswith("block")]

# NEW (v6 uses integer status codes; 1,4,5,6,10,12,13,14,15 are blocked):
_BLOCKED_STATUSES = {1, 4, 5, 6, 10, 12, 13, 14, 15}
blocked = [q for q in queries if q.get("status") in _BLOCKED_STATUSES]
```

Add the constant at module level in `src/tools/pihole.py` (top, after imports):

```python
_BLOCKED_STATUSES = {1, 4, 5, 6, 10, 12, 13, 14, 15}
```

And update the filter in `test_dns_resolution` to reference it.

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass. If any fail, fix before continuing.

- [ ] **Step 5: Commit**

```bash
git add src/server.py src/tools/pihole.py tests/test_pihole.py
git commit -m "fix: pihole singleton removed; tests rewritten for v6 API"
```

---

### Task 2: get_query_log

**Files:**
- Modify: `src/tools/pihole.py` — add `get_query_log()`
- Modify: `src/server.py` — register tool
- Modify: `tests/test_pihole.py` — add tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pihole.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_pihole.py::test_get_query_log_default -v
```

Expected: `AttributeError: 'PiholeClient' object has no attribute 'get_query_log'`

- [ ] **Step 3: Implement get_query_log in pihole.py**

Add after `test_dns_resolution` in `PiholeClient`:

```python
_STATUS_NAMES = {
    1: "blocked", 2: "forwarded", 3: "cached", 4: "blocked",
    5: "blocked", 6: "blocked", 7: "forwarded", 8: "forwarded",
    9: "forwarded", 10: "blocked", 11: "forwarded", 12: "blocked",
    13: "blocked", 14: "blocked", 15: "blocked",
}

def get_query_log(
    self,
    blocked: bool | None = None,
    domain: str | None = None,
    client: str | None = None,
    limit: int = 50,
) -> dict:
    url = f"{self._base}/queries"
    params: dict = {"limit": limit}
    if blocked is not None:
        params["blocked"] = str(blocked).lower()
    if domain:
        params["domain"] = domain
    if client:
        params["client"] = client
    try:
        with httpx.Client(timeout=10) as c:
            sid = self._get_sid(c)
            if sid is None:
                return {"success": False, "error": "Authentication failed",
                        "suggestion": "Check api_token in config.json", "attempted": url}
            resp = c.get(url, headers={"X-FTL-SID": sid}, params=params)
            resp.raise_for_status()
        queries = []
        for q in resp.json().get("queries", []):
            client_info = q.get("client", {})
            queries.append({
                "domain": q.get("domain", ""),
                "client": client_info.get("ip", "") if isinstance(client_info, dict) else str(client_info),
                "client_name": client_info.get("name", "") if isinstance(client_info, dict) else "",
                "status": _STATUS_NAMES.get(q.get("status"), "unknown"),
                "type": q.get("type", ""),
                "timestamp": q.get("time", 0),
            })
        return {"success": True, "queries": queries, "count": len(queries)}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}",
                "suggestion": "Check Pi-hole host in config.json", "attempted": url}
    except httpx.ConnectError as e:
        return {"success": False, "error": str(e),
                "suggestion": f"Cannot reach Pi-hole at {self.host}", "attempted": url}
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "", "attempted": url}
```

Also add `_STATUS_NAMES` dict at module level (top of file, after `_BLOCKED_STATUSES`).

- [ ] **Step 4: Register tool in server.py**

Add after the `get_pihole_stats` tool:

```python
@mcp.tool()
def get_query_log(
    blocked: bool | None = None,
    domain: str | None = None,
    client: str | None = None,
    limit: int = 50,
) -> dict:
    """Get recent DNS query log. Filter by blocked=True for only blocked queries, domain or client for specific lookups."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_query_log(blocked=blocked, domain=domain, client=client, limit=limit)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_pihole.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/tools/pihole.py src/server.py tests/test_pihole.py
git commit -m "feat: add get_query_log tool"
```

---

### Task 3: get_top_domains + get_top_clients

**Files:**
- Modify: `src/tools/pihole.py`
- Modify: `src/server.py`
- Modify: `tests/test_pihole.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pihole.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_pihole.py::test_get_top_domains_allowed tests/test_pihole.py::test_get_top_clients -v
```

Expected: `AttributeError`

- [ ] **Step 3: Implement both methods in pihole.py**

Add to `PiholeClient`:

```python
def get_top_domains(self, blocked: bool = False, count: int = 10) -> dict:
    url = f"{self._base}/stats/top_domains"
    params = {"count": count, "blocked": str(blocked).lower()}
    try:
        with httpx.Client(timeout=10) as c:
            sid = self._get_sid(c)
            if sid is None:
                return {"success": False, "error": "Authentication failed",
                        "suggestion": "Check api_token in config.json", "attempted": url}
            resp = c.get(url, headers={"X-FTL-SID": sid}, params=params)
            resp.raise_for_status()
        raw = resp.json().get("domains", {})
        domains = [{"domain": k, "count": v} for k, v in sorted(raw.items(), key=lambda x: -x[1])]
        return {"success": True, "domains": domains, "blocked_filter": blocked}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}",
                "suggestion": "Check Pi-hole host in config.json", "attempted": url}
    except httpx.ConnectError as e:
        return {"success": False, "error": str(e),
                "suggestion": f"Cannot reach Pi-hole at {self.host}", "attempted": url}
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

def get_top_clients(self, count: int = 10) -> dict:
    url = f"{self._base}/stats/top_clients"
    try:
        with httpx.Client(timeout=10) as c:
            sid = self._get_sid(c)
            if sid is None:
                return {"success": False, "error": "Authentication failed",
                        "suggestion": "Check api_token in config.json", "attempted": url}
            resp = c.get(url, headers={"X-FTL-SID": sid}, params={"count": count})
            resp.raise_for_status()
        raw = resp.json().get("clients", {})
        clients = []
        for key, cnt in sorted(raw.items(), key=lambda x: -x[1]):
            ip, _, name = key.partition("|")
            clients.append({"ip": ip, "name": name, "count": cnt})
        return {"success": True, "clients": clients}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}",
                "suggestion": "Check Pi-hole host in config.json", "attempted": url}
    except httpx.ConnectError as e:
        return {"success": False, "error": str(e),
                "suggestion": f"Cannot reach Pi-hole at {self.host}", "attempted": url}
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "", "attempted": url}
```

- [ ] **Step 4: Register tools in server.py**

```python
@mcp.tool()
def get_top_domains(blocked: bool = False, count: int = 10) -> dict:
    """Get top queried domains. Set blocked=True for top blocked domains."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_top_domains(blocked=blocked, count=count)


@mcp.tool()
def get_top_clients(count: int = 10) -> dict:
    """Get clients with the most DNS queries today."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_top_clients(count=count)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_pihole.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/tools/pihole.py src/server.py tests/test_pihole.py
git commit -m "feat: add get_top_domains and get_top_clients tools"
```

---

### Task 4: get_domain_lists + get_clients

**Files:**
- Modify: `src/tools/pihole.py`
- Modify: `src/server.py`
- Modify: `tests/test_pihole.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pihole.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_pihole.py::test_get_domain_lists tests/test_pihole.py::test_get_clients -v
```

Expected: `AttributeError`

- [ ] **Step 3: Implement both methods in pihole.py**

```python
def get_domain_lists(self) -> dict:
    url = f"{self._base}/domains"
    try:
        with httpx.Client(timeout=10) as c:
            sid = self._get_sid(c)
            if sid is None:
                return {"success": False, "error": "Authentication failed",
                        "suggestion": "Check api_token in config.json", "attempted": url}
            resp = c.get(url, headers={"X-FTL-SID": sid})
            resp.raise_for_status()
        allow, block = [], []
        for entry in resp.json().get("domains", []):
            item = {
                "domain": entry.get("domain", ""),
                "kind": "regex" if entry.get("kind") == 1 else "exact",
                "enabled": entry.get("enabled", True),
                "comment": entry.get("comment", ""),
            }
            if entry.get("type") == 0:
                allow.append(item)
            else:
                block.append(item)
        return {"success": True, "allow": allow, "block": block}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}",
                "suggestion": "Check Pi-hole host in config.json", "attempted": url}
    except httpx.ConnectError as e:
        return {"success": False, "error": str(e),
                "suggestion": f"Cannot reach Pi-hole at {self.host}", "attempted": url}
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

def get_clients(self) -> dict:
    url = f"{self._base}/clients"
    try:
        with httpx.Client(timeout=10) as c:
            sid = self._get_sid(c)
            if sid is None:
                return {"success": False, "error": "Authentication failed",
                        "suggestion": "Check api_token in config.json", "attempted": url}
            resp = c.get(url, headers={"X-FTL-SID": sid})
            resp.raise_for_status()
        clients = []
        for entry in resp.json().get("clients", []):
            clients.append({
                "ip": entry.get("ip", ""),
                "hostname": entry.get("name", ""),
                "query_count": entry.get("count", 0),
                "last_query": entry.get("last_query", 0),
            })
        return {"success": True, "clients": clients}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}",
                "suggestion": "Check Pi-hole host in config.json", "attempted": url}
    except httpx.ConnectError as e:
        return {"success": False, "error": str(e),
                "suggestion": f"Cannot reach Pi-hole at {self.host}", "attempted": url}
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "", "attempted": url}
```

- [ ] **Step 4: Register tools in server.py**

```python
@mcp.tool()
def get_domain_lists() -> dict:
    """Get all Pi-hole allowlist and blocklist entries (exact and regex)."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_domain_lists()


@mcp.tool()
def get_clients() -> dict:
    """Get all DNS clients Pi-hole has seen, with query counts and hostnames."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_clients()
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_pihole.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/tools/pihole.py src/server.py tests/test_pihole.py
git commit -m "feat: add get_domain_lists and get_clients tools"
```

---

### Task 5: get_pihole_system

**Files:**
- Modify: `src/tools/pihole.py`
- Modify: `src/server.py`
- Modify: `tests/test_pihole.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pihole.py`:

```python
@respx.mock
def test_get_pihole_system(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/info/system").mock(
        return_value=httpx.Response(200, json={"system": {
            "cpu": {"nprocs": 4, "load": {"raw": [0.12, 0.08, 0.05]}},
            "memory": {"ram": {"total": 4000000000, "used": 800000000, "free": 3200000000}},
            "uptime": 86400,
            "hostname": "pihole",
        }})
    )
    result = client.get_pihole_system()
    assert result["success"] is True
    assert result["hostname"] == "pihole"
    assert result["uptime_seconds"] == 86400
    assert result["cpu_load_1m"] == 0.12
    assert "ram_used_mb" in result
    assert "ram_total_mb" in result


@respx.mock
def test_get_pihole_system_http_error(client):
    _mock_auth()
    respx.get("http://192.168.0.10/api/info/system").mock(
        return_value=httpx.Response(500)
    )
    result = client.get_pihole_system()
    assert result["success"] is False
```

- [ ] **Step 2: Verify they fail**

```bash
.venv/bin/pytest tests/test_pihole.py::test_get_pihole_system -v
```

Expected: `AttributeError`

- [ ] **Step 3: Implement get_pihole_system**

```python
def get_pihole_system(self) -> dict:
    url = f"{self._base}/info/system"
    try:
        with httpx.Client(timeout=10) as c:
            sid = self._get_sid(c)
            if sid is None:
                return {"success": False, "error": "Authentication failed",
                        "suggestion": "Check api_token in config.json", "attempted": url}
            resp = c.get(url, headers={"X-FTL-SID": sid})
            resp.raise_for_status()
        sys = resp.json().get("system", {})
        cpu = sys.get("cpu", {})
        mem = sys.get("memory", {}).get("ram", {})
        load_raw = cpu.get("load", {}).get("raw", [0, 0, 0])
        return {
            "success": True,
            "hostname": sys.get("hostname", ""),
            "uptime_seconds": sys.get("uptime", 0),
            "cpu_load_1m": load_raw[0] if len(load_raw) > 0 else 0,
            "cpu_load_5m": load_raw[1] if len(load_raw) > 1 else 0,
            "cpu_load_15m": load_raw[2] if len(load_raw) > 2 else 0,
            "ram_total_mb": round(mem.get("total", 0) / 1_000_000),
            "ram_used_mb": round(mem.get("used", 0) / 1_000_000),
            "ram_free_mb": round(mem.get("free", 0) / 1_000_000),
        }
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}",
                "suggestion": "Check Pi-hole host in config.json", "attempted": url}
    except httpx.ConnectError as e:
        return {"success": False, "error": str(e),
                "suggestion": f"Cannot reach Pi-hole at {self.host}", "attempted": url}
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "", "attempted": url}
```

- [ ] **Step 4: Register tool in server.py**

```python
@mcp.tool()
def get_pihole_system() -> dict:
    """Get Pi-hole system info: CPU load, RAM usage, uptime, hostname."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_pihole_system()
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_pihole.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/tools/pihole.py src/server.py tests/test_pihole.py
git commit -m "feat: add get_pihole_system tool"
```

---

### Task 6: add_domain + remove_domain

**Files:**
- Modify: `src/tools/pihole.py`
- Modify: `src/server.py`
- Modify: `tests/test_pihole.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pihole.py`:

```python
@respx.mock
def test_add_domain_allowlist(client):
    _mock_auth()
    respx.post("http://192.168.0.10/api/domains/allow/exact").mock(
        return_value=httpx.Response(201, json={"domains": [
            {"domain": "safe.com", "type": 0, "kind": 0, "enabled": True, "comment": "my note"}
        ]})
    )
    result = client.add_domain("safe.com", list_type="allow", comment="my note")
    assert result["success"] is True
    assert result["domain"] == "safe.com"
    assert result["list_type"] == "allow"


@respx.mock
def test_add_domain_blocklist_regex(client):
    _mock_auth()
    respx.post("http://192.168.0.10/api/domains/block/regex").mock(
        return_value=httpx.Response(201, json={"domains": [
            {"domain": r"^ads\.", "type": 1, "kind": 1, "enabled": True, "comment": ""}
        ]})
    )
    result = client.add_domain(r"^ads\.", list_type="block", kind="regex")
    assert result["success"] is True
    assert result["list_type"] == "block"
    assert result["kind"] == "regex"


@respx.mock
def test_add_domain_conflict(client):
    _mock_auth()
    respx.post("http://192.168.0.10/api/domains/allow/exact").mock(
        return_value=httpx.Response(409, json={"error": "already exists"})
    )
    result = client.add_domain("safe.com", list_type="allow")
    assert result["success"] is False
    assert "409" in result["error"]


@respx.mock
def test_remove_domain(client):
    _mock_auth()
    respx.delete("http://192.168.0.10/api/domains/block/exact/ads.evil.com").mock(
        return_value=httpx.Response(204)
    )
    result = client.remove_domain("ads.evil.com", list_type="block")
    assert result["success"] is True
    assert result["domain"] == "ads.evil.com"


@respx.mock
def test_remove_domain_not_found(client):
    _mock_auth()
    respx.delete("http://192.168.0.10/api/domains/block/exact/notexist.com").mock(
        return_value=httpx.Response(404)
    )
    result = client.remove_domain("notexist.com", list_type="block")
    assert result["success"] is False
    assert "404" in result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_pihole.py::test_add_domain_allowlist tests/test_pihole.py::test_remove_domain -v
```

Expected: `AttributeError`

- [ ] **Step 3: Implement add_domain + remove_domain**

```python
def add_domain(
    self,
    domain: str,
    list_type: str = "block",
    kind: str = "exact",
    comment: str = "",
) -> dict:
    url = f"{self._base}/domains/{list_type}/{kind}"
    try:
        with httpx.Client(timeout=10) as c:
            sid = self._get_sid(c)
            if sid is None:
                return {"success": False, "error": "Authentication failed",
                        "suggestion": "Check api_token in config.json", "attempted": url}
            resp = c.post(url, headers={"X-FTL-SID": sid},
                          json={"domain": domain, "comment": comment, "enabled": True})
            resp.raise_for_status()
        return {"success": True, "domain": domain, "list_type": list_type, "kind": kind}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}",
                "suggestion": "Domain may already exist" if e.response.status_code == 409 else "Check Pi-hole host in config.json",
                "attempted": url}
    except httpx.ConnectError as e:
        return {"success": False, "error": str(e),
                "suggestion": f"Cannot reach Pi-hole at {self.host}", "attempted": url}
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

def remove_domain(
    self,
    domain: str,
    list_type: str = "block",
    kind: str = "exact",
) -> dict:
    url = f"{self._base}/domains/{list_type}/{kind}/{domain}"
    try:
        with httpx.Client(timeout=10) as c:
            sid = self._get_sid(c)
            if sid is None:
                return {"success": False, "error": "Authentication failed",
                        "suggestion": "Check api_token in config.json", "attempted": url}
            resp = c.delete(url, headers={"X-FTL-SID": sid})
            resp.raise_for_status()
        return {"success": True, "domain": domain, "list_type": list_type, "kind": kind}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}",
                "suggestion": "Domain not found in list" if e.response.status_code == 404 else "Check Pi-hole host in config.json",
                "attempted": url}
    except httpx.ConnectError as e:
        return {"success": False, "error": str(e),
                "suggestion": f"Cannot reach Pi-hole at {self.host}", "attempted": url}
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "", "attempted": url}
```

- [ ] **Step 4: Register tools in server.py**

```python
@mcp.tool()
def add_domain(
    domain: str,
    list_type: str = "block",
    kind: str = "exact",
    comment: str = "",
) -> dict:
    """Add a domain to Pi-hole's allowlist or blocklist. list_type: 'allow' or 'block'. kind: 'exact' or 'regex'."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).add_domain(domain, list_type=list_type, kind=kind, comment=comment)


@mcp.tool()
def remove_domain(
    domain: str,
    list_type: str = "block",
    kind: str = "exact",
) -> dict:
    """Remove a domain from Pi-hole's allowlist or blocklist."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).remove_domain(domain, list_type=list_type, kind=kind)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_pihole.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/tools/pihole.py src/server.py tests/test_pihole.py
git commit -m "feat: add add_domain and remove_domain tools"
```

---

### Task 7: set_blocking + update_gravity

**Files:**
- Modify: `src/tools/pihole.py`
- Modify: `src/server.py`
- Modify: `tests/test_pihole.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pihole.py`:

```python
@respx.mock
def test_set_blocking_disable(client):
    _mock_auth()
    respx.post("http://192.168.0.10/api/dns/blocking").mock(
        return_value=httpx.Response(200, json={"blocking": "disabled", "timer": None})
    )
    result = client.set_blocking(enabled=False)
    assert result["success"] is True
    assert result["blocking"] == "disabled"


@respx.mock
def test_set_blocking_enable_with_timer(client):
    _mock_auth()
    respx.post("http://192.168.0.10/api/dns/blocking").mock(
        return_value=httpx.Response(200, json={"blocking": "disabled", "timer": 300})
    )
    result = client.set_blocking(enabled=False, timer=300)
    assert result["success"] is True
    assert result["timer"] == 300


@respx.mock
def test_set_blocking_http_error(client):
    _mock_auth()
    respx.post("http://192.168.0.10/api/dns/blocking").mock(
        return_value=httpx.Response(500)
    )
    result = client.set_blocking(enabled=True)
    assert result["success"] is False


@respx.mock
def test_update_gravity(client):
    _mock_auth()
    respx.post("http://192.168.0.10/api/gravity").mock(
        return_value=httpx.Response(200, json={"status": "running"})
    )
    result = client.update_gravity()
    assert result["success"] is True
    assert "triggered" in result["message"].lower()


@respx.mock
def test_update_gravity_http_error(client):
    _mock_auth()
    respx.post("http://192.168.0.10/api/gravity").mock(
        return_value=httpx.Response(500)
    )
    result = client.update_gravity()
    assert result["success"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_pihole.py::test_set_blocking_disable tests/test_pihole.py::test_update_gravity -v
```

Expected: `AttributeError`

- [ ] **Step 3: Implement both methods**

```python
def set_blocking(self, enabled: bool, timer: int | None = None) -> dict:
    url = f"{self._base}/dns/blocking"
    body: dict = {"blocking": "enabled" if enabled else "disabled"}
    if timer is not None:
        body["timer"] = timer
    try:
        with httpx.Client(timeout=10) as c:
            sid = self._get_sid(c)
            if sid is None:
                return {"success": False, "error": "Authentication failed",
                        "suggestion": "Check api_token in config.json", "attempted": url}
            resp = c.post(url, headers={"X-FTL-SID": sid}, json=body)
            resp.raise_for_status()
        data = resp.json()
        return {
            "success": True,
            "blocking": data.get("blocking", ""),
            "timer": data.get("timer"),
        }
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}",
                "suggestion": "Check Pi-hole host in config.json", "attempted": url}
    except httpx.ConnectError as e:
        return {"success": False, "error": str(e),
                "suggestion": f"Cannot reach Pi-hole at {self.host}", "attempted": url}
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

def update_gravity(self) -> dict:
    url = f"{self._base}/gravity"
    try:
        with httpx.Client(timeout=15) as c:
            sid = self._get_sid(c)
            if sid is None:
                return {"success": False, "error": "Authentication failed",
                        "suggestion": "Check api_token in config.json", "attempted": url}
            resp = c.post(url, headers={"X-FTL-SID": sid})
            resp.raise_for_status()
        return {"success": True, "message": "Gravity update triggered — runs in background on Pi-hole"}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}",
                "suggestion": "Check Pi-hole host in config.json", "attempted": url}
    except httpx.ConnectError as e:
        return {"success": False, "error": str(e),
                "suggestion": f"Cannot reach Pi-hole at {self.host}", "attempted": url}
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "", "attempted": url}
```

- [ ] **Step 4: Register tools in server.py**

```python
@mcp.tool()
def set_blocking(enabled: bool, timer: int | None = None) -> dict:
    """Enable or disable Pi-hole ad blocking. Optionally set timer (seconds) to auto-re-enable."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).set_blocking(enabled=enabled, timer=timer)


@mcp.tool()
def update_gravity() -> dict:
    """Trigger a Pi-hole gravity update to refresh blocklists. Runs asynchronously on the Pi."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).update_gravity()
```

- [ ] **Step 5: Run all tests**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/tools/pihole.py src/server.py tests/test_pihole.py
git commit -m "feat: add set_blocking and update_gravity tools"
```

---

### Task 8: Update test_server.py + final verification

**Files:**
- Modify: `tests/test_server.py`

- [ ] **Step 1: Update EXPECTED_TOOLS in test_server.py**

Replace the `EXPECTED_TOOLS` list:

```python
EXPECTED_TOOLS = [
    "get_wan_status",
    "get_router_info",
    "get_connected_clients",
    "get_mesh_health",
    "get_pihole_stats",
    "get_query_log",
    "get_top_domains",
    "get_top_clients",
    "get_domain_lists",
    "get_clients",
    "get_pihole_system",
    "add_domain",
    "remove_domain",
    "set_blocking",
    "update_gravity",
    "test_dns_resolution",
    "ping_host",
    "traceroute_host",
    "run_speedtest",
]
```

- [ ] **Step 2: Run full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass. Count should be 34 original + ~30 new = ~64 tests.

- [ ] **Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test: update expected tools list for Phase 2"
```
