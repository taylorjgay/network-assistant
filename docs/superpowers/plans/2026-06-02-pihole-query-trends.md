# Pi-hole Query Trends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `get_query_trends` MCP tool that returns 24 hours of hourly DNS query volume with automatic spike detection (hours >2× the average).

**Architecture:** One new method `get_query_trends()` on `PiholeClient` in `src/tools/pihole.py`, registered in `src/server.py`. No new files. Tests appended to `tests/test_pihole.py`.

**Tech Stack:** Python 3.11, httpx, respx (mock), pytest, Pi-hole v6 `/api/history` endpoint

---

## File Map

- **Modify:** `src/tools/pihole.py` — add imports, add `get_query_trends()` method
- **Modify:** `src/server.py` — register `get_query_trends` tool
- **Modify:** `tests/test_pihole.py` — append 4 tests
- **Modify:** `tests/test_server.py` — update `EXPECTED_TOOLS` from 30 → 31

## Environment

```bash
.venv/bin/pytest tests/test_pihole.py -v     # Pi-hole tests only
.venv/bin/pytest -v                           # all tests
```

## Existing test fixtures (already in tests/test_pihole.py — do NOT redefine)

```python
@pytest.fixture
def client():
    return PiholeClient(host="192.168.0.10", api_token="testtoken")

def _mock_auth():
    respx.post("http://192.168.0.10/api/auth").mock(
        return_value=httpx.Response(200, json={"session": {"valid": True, "sid": "test-sid"}})
    )
```

## Key Pi-hole v6 API facts

- Auth: `POST /api/auth` with `{"password": api_token}` → `{"session": {"valid": True, "sid": "..."}}`
- All authenticated requests use `X-FTL-SID: <sid>` header
- History endpoint: `GET /api/history` → `{"history": [{"timestamp": int, "total": int, "blocked": int}, ...]}`
- Returns 144 points at 10-minute intervals (24 hours of data)
- `error_code` pattern not used for Pi-hole — uses HTTP status codes

---

### Task 1: get_query_trends + tests

**Files:**
- Modify: `src/tools/pihole.py` — add 2 imports, append `get_query_trends()` after `get_clients()`
- Modify: `tests/test_pihole.py` — append 4 tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pihole.py`:

```python
# --- get_query_trends ---

HISTORY_URL = "http://192.168.0.10/api/history"


@respx.mock
def test_get_query_trends_success(client):
    _mock_auth()
    # 6 points per hour × 2 hours at 10-min intervals
    history = []
    for i in range(6):
        history.append({"timestamp": 1717200000 + i * 600, "total": 20, "blocked": 5})
    for i in range(6):
        history.append({"timestamp": 1717203600 + i * 600, "total": 30, "blocked": 10})
    respx.get(HISTORY_URL).mock(return_value=httpx.Response(200, json={"history": history}))

    result = client.get_query_trends()

    assert result["success"] is True
    assert len(result["hours"]) == 2
    assert result["hours"][0]["total"] == 120    # 6 × 20
    assert result["hours"][0]["blocked"] == 30   # 6 × 5
    assert result["hours"][0]["block_pct"] == 25.0
    assert result["hours"][1]["total"] == 180    # 6 × 30
    assert result["summary"]["total_24h"] == 300
    assert result["summary"]["blocked_24h"] == 90
    assert result["summary"]["avg_per_hour"] == 150.0


@respx.mock
def test_get_query_trends_spike_detected(client):
    _mock_auth()
    # avg = (10 + 200 + 10) / 3 ≈ 73.3; spike threshold = 146.7; hour 2 (200) exceeds it
    history = [
        {"timestamp": 1717200000, "total": 10, "blocked": 1},
        {"timestamp": 1717203600, "total": 200, "blocked": 50},
        {"timestamp": 1717207200, "total": 10, "blocked": 1},
    ]
    respx.get(HISTORY_URL).mock(return_value=httpx.Response(200, json={"history": history}))

    result = client.get_query_trends()

    assert result["success"] is True
    spike_hour = next(h for h in result["hours"] if h["is_spike"])
    assert spike_hour["total"] == 200
    assert len(result["summary"]["spike_hours"]) == 1
    non_spikes = [h for h in result["hours"] if not h["is_spike"]]
    assert len(non_spikes) == 2


@respx.mock
def test_get_query_trends_empty_history(client):
    _mock_auth()
    respx.get(HISTORY_URL).mock(return_value=httpx.Response(200, json={"history": []}))

    result = client.get_query_trends()

    assert result["success"] is True
    assert result["hours"] == []
    assert result["summary"]["total_24h"] == 0
    assert result["summary"]["blocked_24h"] == 0
    assert result["summary"]["spike_hours"] == []


@respx.mock
def test_get_query_trends_auth_failure(client):
    respx.post("http://192.168.0.10/api/auth").mock(
        return_value=httpx.Response(200, json={"session": {"valid": False}})
    )

    result = client.get_query_trends()

    assert result["success"] is False
    assert "Authentication failed" in result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_pihole.py::test_get_query_trends_success tests/test_pihole.py::test_get_query_trends_spike_detected tests/test_pihole.py::test_get_query_trends_empty_history tests/test_pihole.py::test_get_query_trends_auth_failure -v
```

Expected: all 4 FAILED — `AttributeError: 'PiholeClient' object has no attribute 'get_query_trends'`

- [ ] **Step 3: Add imports to src/tools/pihole.py**

Read the file first. The current imports are just `import httpx`. Add at the top:

```python
from collections import defaultdict
from datetime import datetime, timezone
import httpx
```

(Replace the existing `import httpx` line — add the two new imports above it.)

- [ ] **Step 4: Implement get_query_trends in src/tools/pihole.py**

Append this method inside `PiholeClient`, after `get_clients()` (at the end of the class):

```python
    def get_query_trends(self) -> dict:
        url = f"{self._base}/history"
        try:
            with httpx.Client(timeout=10) as client:
                sid = self._get_sid(client)
                if sid is None:
                    return {"success": False, "error": "Authentication failed",
                            "suggestion": "Check api_token in config.json", "attempted": url}
                resp = client.get(url, headers={"X-FTL-SID": sid})
                resp.raise_for_status()
                history = resp.json().get("history", [])

            buckets: dict = defaultdict(lambda: {"total": 0, "blocked": 0})
            for point in history:
                hour_ts = (point["timestamp"] // 3600) * 3600
                buckets[hour_ts]["total"] += point.get("total", 0)
                buckets[hour_ts]["blocked"] += point.get("blocked", 0)

            total_24h = 0
            blocked_24h = 0
            hours = []
            for ts in sorted(buckets):
                t = buckets[ts]["total"]
                b = buckets[ts]["blocked"]
                total_24h += t
                blocked_24h += b
                hours.append({
                    "hour": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "total": t,
                    "blocked": b,
                    "block_pct": round(b / t * 100, 1) if t > 0 else 0.0,
                    "is_spike": False,
                })

            avg_per_hour = round(total_24h / len(hours), 1) if hours else 0.0
            spike_hours = []
            for h in hours:
                if h["total"] > 2 * avg_per_hour:
                    h["is_spike"] = True
                    spike_hours.append(h["hour"])

            return {
                "success": True,
                "hours": hours,
                "summary": {
                    "total_24h": total_24h,
                    "blocked_24h": blocked_24h,
                    "block_pct_24h": round(blocked_24h / total_24h * 100, 1) if total_24h > 0 else 0.0,
                    "avg_per_hour": avg_per_hour,
                    "spike_hours": spike_hours,
                },
            }
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"HTTP {e.response.status_code}",
                    "suggestion": "Check Pi-hole host in config.json", "attempted": url}
        except httpx.ConnectError as e:
            return {"success": False, "error": str(e),
                    "suggestion": f"Cannot reach Pi-hole at {self.host} — verify IP in config.json",
                    "attempted": url}
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_pihole.py::test_get_query_trends_success tests/test_pihole.py::test_get_query_trends_spike_detected tests/test_pihole.py::test_get_query_trends_empty_history tests/test_pihole.py::test_get_query_trends_auth_failure -v
```

Expected: all 4 PASSED.

- [ ] **Step 6: Run full pihole test suite to confirm no regressions**

```bash
.venv/bin/pytest tests/test_pihole.py -v 2>&1 | tail -10
```

Expected: all tests pass (previous count + 4 new).

- [ ] **Step 7: Commit**

```bash
git add src/tools/pihole.py tests/test_pihole.py
git commit -m "feat: add get_query_trends to PiholeClient"
```

---

### Task 2: Register in server.py + update test_server.py

**Files:**
- Modify: `src/server.py` — register `get_query_trends` tool after `update_gravity`
- Modify: `tests/test_server.py` — add `"get_query_trends"` to `EXPECTED_TOOLS`

- [ ] **Step 1: Read src/server.py**

Find the `update_gravity` tool (currently the last Pi-hole tool). Add the new tool immediately after it.

- [ ] **Step 2: Add get_query_trends tool to src/server.py**

Add after the `update_gravity` tool:

```python
@mcp.tool()
def get_query_trends() -> dict:
    """Get 24 hours of hourly DNS query volume (total + blocked per hour) and flag spike hours (>2× average)."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_query_trends()
```

- [ ] **Step 3: Read tests/test_server.py**

Find the current `EXPECTED_TOOLS` list (30 items).

- [ ] **Step 4: Add get_query_trends to EXPECTED_TOOLS**

Add `"get_query_trends"` to the list. Place it after `"update_gravity"`:

```python
EXPECTED_TOOLS = [
    "get_wan_status", "get_router_info",
    "get_wan_policy", "set_wan_priority",
    "get_port_forwards", "add_port_forward", "remove_port_forward",
    "get_firewall_rules", "add_firewall_rule", "remove_firewall_rule",
    "get_network_devices", "label_device", "remove_device_label",
    "get_connected_clients", "get_mesh_health",
    "get_pihole_stats", "get_query_log", "get_top_domains", "get_top_clients",
    "get_domain_lists", "get_clients", "get_pihole_system", "add_domain",
    "remove_domain", "set_blocking", "update_gravity", "get_query_trends",
    "test_dns_resolution", "ping_host", "traceroute_host", "run_speedtest",
]
```

- [ ] **Step 5: Run the full test suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -15
```

Expected: all tests pass. New total: ~116 tests (112 existing + 4 new).

- [ ] **Step 6: Commit**

```bash
git add src/server.py tests/test_server.py
git commit -m "feat: register get_query_trends MCP tool"
```
