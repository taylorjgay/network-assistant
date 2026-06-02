# WAN Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two MCP tools — `get_wan_health` (safe always-on snapshot of both WAN interfaces + active probe) and `compare_wan_health` (temporarily forces each WAN to measure independent health).

**Architecture:** New `src/tools/wan_health.py` with a `WANHealthClient` class. Composes a fresh `ER605Client` per internal call for API data and WAN switching, and `subprocess` pings for latency/loss measurement. Two methods map to two MCP tools registered in `src/server.py`.

**Tech Stack:** Python 3.11, httpx (via ER605Client), subprocess (ping), concurrent.futures.ThreadPoolExecutor, respx + unittest.mock (tests)

---

## File Map

- **Create:** `src/tools/wan_health.py` — `WANHealthClient` class with `get_wan_health()` and `compare_wan_health()`
- **Create:** `tests/test_wan_health.py` — ~15 tests
- **Modify:** `src/server.py` — import `WANHealthClient`, register 2 tools
- **Modify:** `tests/test_server.py` — add 2 entries to `EXPECTED_TOOLS`

## Environment

```bash
.venv/bin/pytest tests/test_wan_health.py -v     # WAN health tests only
.venv/bin/pytest -v                               # all tests
```

## Key facts about existing code

**`ER605Client.get_wan_status()` returns:**
```python
{
    "success": True,
    "interfaces": [
        {"name": "WAN1", "up": True, "ip": "192.168.1.70", "proto": "dhcp",
         "gateway": "192.168.1.254", "dns1": "8.8.8.8"},
        {"name": "WAN2", "up": True, "ip": "192.168.12.153", ...},
    ]
}
```

**`ER605Client.get_wan_policy()` returns:**
```python
{"success": True, "mode": "load_balance", "primary_wan": "WAN1", "health_check": {}}
```

**`ER605Client.set_wan_priority(primary_wan)` returns:**
```python
{"success": True, "primary_wan": "WAN1"}  # or error dict
```

**Ping stdout format parsed in `diagnostics.py`:**
```
5 packets transmitted, 5 received, 0.0% packet loss
round-trip min/avg/max/stddev = 10.0/14.2/18.5/2.1 ms
```

---

### Task 1: WANHealthClient + get_wan_health + tests

**Files:**
- Create: `src/tools/wan_health.py`
- Create: `tests/test_wan_health.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_wan_health.py`:

```python
import pytest
from unittest.mock import patch
from src.tools.wan_health import WANHealthClient
from src.tools.er605 import ER605Client


@pytest.fixture
def client():
    return WANHealthClient(host="192.168.0.1", username="admin", password="secret")


def _iface_result(wan1_up=True, wan2_up=True):
    return {
        "success": True,
        "interfaces": [
            {"name": "WAN1", "up": wan1_up,
             "ip": "192.168.1.70" if wan1_up else "",
             "gateway": "192.168.1.254", "proto": "dhcp", "dns1": "8.8.8.8"},
            {"name": "WAN2", "up": wan2_up,
             "ip": "192.168.12.153" if wan2_up else "",
             "gateway": "192.168.12.1", "proto": "dhcp", "dns1": "8.8.8.8"},
        ],
    }


GOOD_PROBE = {
    "targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"],
    "avg_latency_ms": 14.2,
    "packet_loss_pct": 0.0,
}
DEGRADED_LOSS_PROBE = {
    "targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"],
    "avg_latency_ms": 14.2,
    "packet_loss_pct": 10.0,
}
DEGRADED_LATENCY_PROBE = {
    "targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"],
    "avg_latency_ms": 200.0,
    "packet_loss_pct": 0.0,
}


def test_get_wan_health_success(client):
    with patch.object(ER605Client, "get_wan_status", return_value=_iface_result()):
        with patch("src.tools.wan_health._probe", return_value=GOOD_PROBE):
            result = client.get_wan_health()

    assert result["success"] is True
    assert result["active_wan"] == "WAN1"
    assert result["wan1"]["link"] == "up"
    assert result["wan1"]["ip"] == "192.168.1.70"
    assert result["wan2"]["link"] == "up"
    assert result["probe"]["avg_latency_ms"] == 14.2
    assert result["probe"]["packet_loss_pct"] == 0.0
    assert result["degraded"] is False


def test_get_wan_health_degraded_packet_loss(client):
    with patch.object(ER605Client, "get_wan_status", return_value=_iface_result()):
        with patch("src.tools.wan_health._probe", return_value=DEGRADED_LOSS_PROBE):
            result = client.get_wan_health()

    assert result["success"] is True
    assert result["degraded"] is True


def test_get_wan_health_degraded_latency(client):
    with patch.object(ER605Client, "get_wan_status", return_value=_iface_result()):
        with patch("src.tools.wan_health._probe", return_value=DEGRADED_LATENCY_PROBE):
            result = client.get_wan_health()

    assert result["success"] is True
    assert result["degraded"] is True


def test_get_wan_health_wan2_active_failover(client):
    with patch.object(ER605Client, "get_wan_status", return_value=_iface_result(wan1_up=False, wan2_up=True)):
        with patch("src.tools.wan_health._probe", return_value=GOOD_PROBE):
            result = client.get_wan_health()

    assert result["success"] is True
    assert result["active_wan"] == "WAN2"
    assert result["wan1"]["link"] == "down"
    assert result["wan1"]["ip"] is None


def test_get_wan_health_er605_auth_failure(client):
    with patch.object(ER605Client, "get_wan_status", return_value={
        "success": False,
        "error": "ER605 authentication failed: bad password",
        "suggestion": "Check er605.username and er605.password in config.json",
        "attempted": "192.168.0.1",
    }):
        result = client.get_wan_health()

    assert result["success"] is False
    assert "authentication failed" in result["error"]


def test_get_wan_health_partial_interface_data(client):
    # Only WAN1 present (WAN2 absent from interfaces list)
    partial = {
        "success": True,
        "interfaces": [
            {"name": "WAN1", "up": True, "ip": "192.168.1.70", "gateway": "192.168.1.254",
             "proto": "dhcp", "dns1": "8.8.8.8"},
        ],
    }
    with patch.object(ER605Client, "get_wan_status", return_value=partial):
        with patch("src.tools.wan_health._probe", return_value=GOOD_PROBE):
            result = client.get_wan_health()

    assert result["success"] is True
    assert result["wan1"]["link"] == "up"
    assert result["wan2"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_wan_health.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.tools.wan_health'`

- [ ] **Step 3: Create src/tools/wan_health.py**

```python
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from src.tools.er605 import ER605Client


_PING_TARGETS = ["1.1.1.1", "8.8.8.8", "8.8.4.4"]
_DEGRADED_LOSS_PCT = 5.0
_DEGRADED_LATENCY_MS = 150.0


def _ping_target(target: str) -> dict:
    try:
        result = subprocess.run(
            ["ping", "-c", "5", "-i", "0.2", target],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout
        loss_match = re.search(r"([\d.]+)% packet loss", output)
        packet_loss = float(loss_match.group(1)) if loss_match else 100.0
        avg_ms = None
        rtt_match = re.search(r"min/avg/max/[^\s]+ = [\d.]+/([\d.]+)/", output)
        if rtt_match:
            avg_ms = float(rtt_match.group(1))
        return {"target": target, "avg_latency_ms": avg_ms, "packet_loss_pct": packet_loss}
    except Exception:
        return {"target": target, "avg_latency_ms": None, "packet_loss_pct": 100.0}


def _probe() -> dict:
    results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_ping_target, t) for t in _PING_TARGETS]
        for f in futures:
            results.append(f.result())
    valid = [r["avg_latency_ms"] for r in results if r["avg_latency_ms"] is not None]
    avg_latency = round(sum(valid) / len(valid), 1) if valid else None
    avg_loss = round(sum(r["packet_loss_pct"] for r in results) / len(results), 1)
    return {
        "targets": _PING_TARGETS,
        "avg_latency_ms": avg_latency,
        "packet_loss_pct": avg_loss,
    }


def _is_degraded(probe: dict) -> bool:
    return (probe.get("packet_loss_pct", 0.0) > _DEGRADED_LOSS_PCT or
            (probe.get("avg_latency_ms") or 0.0) > _DEGRADED_LATENCY_MS)


class WANHealthClient:
    def __init__(self, host: str, username: str, password: str):
        self._kwargs = {"host": host, "username": username, "password": password}

    def _er605(self) -> ER605Client:
        return ER605Client(**self._kwargs)

    def get_wan_health(self) -> dict:
        url = self._kwargs["host"]
        try:
            wan_status = self._er605().get_wan_status()
            if not wan_status["success"]:
                return wan_status

            ifaces = {i["name"]: i for i in wan_status.get("interfaces", [])}

            def _parse(name: str) -> dict | None:
                i = ifaces.get(name)
                if i is None:
                    return None
                return {
                    "link": "up" if i.get("up") else "down",
                    "ip": i.get("ip") or None,
                    "gateway": i.get("gateway") or None,
                    "bytes_in": i.get("bytes_in"),
                    "bytes_out": i.get("bytes_out"),
                }

            wan1 = _parse("WAN1")
            wan2 = _parse("WAN2")

            active_wan = None
            if wan1 and wan1["link"] == "up" and wan1["ip"]:
                active_wan = "WAN1"
            elif wan2 and wan2["link"] == "up" and wan2["ip"]:
                active_wan = "WAN2"

            probe = _probe()
            return {
                "success": True,
                "active_wan": active_wan,
                "wan1": wan1,
                "wan2": wan2,
                "probe": probe,
                "degraded": _is_degraded(probe),
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_wan_health.py -v
```

Expected: all 6 PASSED.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
.venv/bin/pytest -v 2>&1 | tail -10
```

Expected: all previous tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/tools/wan_health.py tests/test_wan_health.py
git commit -m "feat: add WANHealthClient and get_wan_health"
```

---

### Task 2: compare_wan_health + tests

**Files:**
- Modify: `src/tools/wan_health.py` — add `compare_wan_health()` method to `WANHealthClient`
- Modify: `tests/test_wan_health.py` — append tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wan_health.py`:

```python
# --- compare_wan_health ---

GOOD_PROBE_WAN1 = {"targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"], "avg_latency_ms": 14.2, "packet_loss_pct": 0.0}
GOOD_PROBE_WAN2 = {"targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"], "avg_latency_ms": 42.1, "packet_loss_pct": 0.0}
DEGRADED_PROBE = {"targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"], "avg_latency_ms": 200.0, "packet_loss_pct": 20.0}


def test_compare_wan_health_wan1_healthier(client):
    with patch.object(ER605Client, "get_wan_policy", return_value={"success": True, "primary_wan": "WAN1"}):
        with patch.object(ER605Client, "set_wan_priority", return_value={"success": True}) as mock_set:
            with patch("src.tools.wan_health._probe", side_effect=[GOOD_PROBE_WAN1, GOOD_PROBE_WAN2]):
                with patch("src.tools.wan_health.time.sleep"):
                    result = client.compare_wan_health()

    assert result["success"] is True
    assert result["original_policy"] == "WAN1"
    assert result["wan1_probe"]["avg_latency_ms"] == 14.2
    assert result["wan1_probe"]["degraded"] is False
    assert result["wan2_probe"]["avg_latency_ms"] == 42.1
    assert result["wan2_probe"]["degraded"] is False
    assert "WAN1" in result["recommendation"]
    assert result["restored"] is True
    assert mock_set.call_count == 3
    calls = [c.args[0] for c in mock_set.call_args_list]
    assert calls == ["WAN1", "WAN2", "WAN1"]


def test_compare_wan_health_wan2_healthier(client):
    with patch.object(ER605Client, "get_wan_policy", return_value={"success": True, "primary_wan": "WAN1"}):
        with patch.object(ER605Client, "set_wan_priority", return_value={"success": True}):
            with patch("src.tools.wan_health._probe", side_effect=[DEGRADED_PROBE, GOOD_PROBE_WAN2]):
                with patch("src.tools.wan_health.time.sleep"):
                    result = client.compare_wan_health()

    assert result["success"] is True
    assert result["wan1_probe"]["degraded"] is True
    assert result["wan2_probe"]["degraded"] is False
    assert "WAN2" in result["recommendation"]


def test_compare_wan_health_both_degraded(client):
    with patch.object(ER605Client, "get_wan_policy", return_value={"success": True, "primary_wan": "WAN1"}):
        with patch.object(ER605Client, "set_wan_priority", return_value={"success": True}):
            with patch("src.tools.wan_health._probe", side_effect=[DEGRADED_PROBE, DEGRADED_PROBE]):
                with patch("src.tools.wan_health.time.sleep"):
                    result = client.compare_wan_health()

    assert result["success"] is True
    assert "Both WANs degraded" in result["recommendation"]


def test_compare_wan_health_restore_on_probe_failure(client):
    with patch.object(ER605Client, "get_wan_policy", return_value={"success": True, "primary_wan": "WAN1"}):
        with patch.object(ER605Client, "set_wan_priority", return_value={"success": True}) as mock_set:
            with patch("src.tools.wan_health._probe", side_effect=Exception("ping failed")):
                with patch("src.tools.wan_health.time.sleep"):
                    result = client.compare_wan_health()

    assert result["success"] is False
    assert result["restored"] is True
    # WAN1 switch (call 1) + WAN1 restore (call 2) — no WAN2 switch since probe failed first
    calls = [c.args[0] for c in mock_set.call_args_list]
    assert calls[-1] == "WAN1"  # last call is restore
    assert mock_set.call_count == 2


def test_compare_wan_health_restored_false_when_restore_fails(client):
    restore_responses = [
        {"success": True},   # WAN1 switch
        {"success": True},   # WAN2 switch
        {"success": False, "error": "ER605 unreachable", "suggestion": "", "attempted": ""},  # restore
    ]
    with patch.object(ER605Client, "get_wan_policy", return_value={"success": True, "primary_wan": "WAN1"}):
        with patch.object(ER605Client, "set_wan_priority", side_effect=restore_responses):
            with patch("src.tools.wan_health._probe", side_effect=[GOOD_PROBE_WAN1, GOOD_PROBE_WAN2]):
                with patch("src.tools.wan_health.time.sleep"):
                    result = client.compare_wan_health()

    assert result["success"] is True
    assert result["restored"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_wan_health.py::test_compare_wan_health_wan1_healthier tests/test_wan_health.py::test_compare_wan_health_wan2_healthier tests/test_wan_health.py::test_compare_wan_health_both_degraded tests/test_wan_health.py::test_compare_wan_health_restore_on_probe_failure tests/test_wan_health.py::test_compare_wan_health_restored_false_when_restore_fails -v
```

Expected: `AttributeError: 'WANHealthClient' object has no attribute 'compare_wan_health'`

- [ ] **Step 3: Add compare_wan_health to WANHealthClient**

Append this method inside `WANHealthClient` in `src/tools/wan_health.py` (after `get_wan_health`):

```python
    def compare_wan_health(self) -> dict:
        url = self._kwargs["host"]
        policy = self._er605().get_wan_policy()
        if not policy["success"]:
            return policy
        original = policy.get("primary_wan", "auto")

        wan1_probe = None
        wan2_probe = None
        error = None
        restored = False
        try:
            r = self._er605().set_wan_priority("WAN1")
            if not r["success"]:
                error = r
            else:
                time.sleep(2)
                raw = _probe()
                wan1_probe = {
                    "avg_latency_ms": raw["avg_latency_ms"],
                    "packet_loss_pct": raw["packet_loss_pct"],
                    "degraded": _is_degraded(raw),
                }
                r = self._er605().set_wan_priority("WAN2")
                if not r["success"]:
                    error = r
                else:
                    time.sleep(2)
                    raw = _probe()
                    wan2_probe = {
                        "avg_latency_ms": raw["avg_latency_ms"],
                        "packet_loss_pct": raw["packet_loss_pct"],
                        "degraded": _is_degraded(raw),
                    }
        except Exception as e:
            error = {"success": False, "error": str(e), "suggestion": "", "attempted": url}
        finally:
            r = self._er605().set_wan_priority(original)
            restored = r.get("success", False)

        if error:
            return {**error, "restored": restored}

        w1_ok = wan1_probe is not None and not wan1_probe["degraded"]
        w2_ok = wan2_probe is not None and not wan2_probe["degraded"]
        if w1_ok and w2_ok:
            l1 = wan1_probe["avg_latency_ms"] or 999
            l2 = wan2_probe["avg_latency_ms"] or 999
            rec = ("Both WANs healthy — WAN1 has lower latency" if l1 <= l2
                   else "Both WANs healthy — WAN2 has lower latency")
        elif w1_ok:
            rec = "WAN1 is healthier — stay on current configuration"
        elif w2_ok:
            rec = "WAN2 is healthier — consider switching primary WAN"
        else:
            rec = "Both WANs degraded — check upstream connections"

        return {
            "success": True,
            "original_policy": original,
            "wan1_probe": wan1_probe,
            "wan2_probe": wan2_probe,
            "recommendation": rec,
            "restored": restored,
        }
```

- [ ] **Step 4: Run all wan_health tests**

```bash
.venv/bin/pytest tests/test_wan_health.py -v
```

Expected: all 11 PASSED.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/tools/wan_health.py tests/test_wan_health.py
git commit -m "feat: add compare_wan_health to WANHealthClient"
```

---

### Task 3: Register tools in server.py + update test_server.py

**Files:**
- Modify: `src/server.py` — import `WANHealthClient`, instantiate singleton, register 2 MCP tools
- Modify: `tests/test_server.py` — add `"get_wan_health"` and `"compare_wan_health"` to `EXPECTED_TOOLS`

- [ ] **Step 1: Read src/server.py**

Find the import block at the top (lines 1–29). Note the existing `_er605` singleton on line 22 and the `_NO_CONFIG` sentinel.

- [ ] **Step 2: Add WANHealthClient import and singleton**

In `src/server.py`, add `WANHealthClient` to the imports and create a singleton. The import block currently ends around line 16. Add:

```python
from src.tools.wan_health import WANHealthClient
```

After `_er605 = ER605Client(**vars(_cfg.er605)) if _cfg else None` (line 22), add:

```python
_wan_health = WANHealthClient(**vars(_cfg.er605)) if _cfg else None
```

- [ ] **Step 3: Register get_wan_health tool**

Add after the `get_wan_policy` tool block:

```python
@mcp.tool()
def get_wan_health() -> dict:
    """Get WAN health: per-interface link status for both WANs plus active latency/packet-loss probe. Sets degraded=True when packet loss >5% or latency >150ms."""
    if not _wan_health:
        return _NO_CONFIG
    return _wan_health.get_wan_health()


@mcp.tool()
def compare_wan_health() -> dict:
    """Compare WAN1 vs WAN2 health by briefly routing through each. WARNING: temporarily disrupts new outbound connections for ~4 seconds total. Only call when investigating suspected WAN degradation."""
    if not _wan_health:
        return _NO_CONFIG
    return _wan_health.compare_wan_health()
```

- [ ] **Step 4: Read tests/test_server.py**

Find the `EXPECTED_TOOLS` list (currently 31 items).

- [ ] **Step 5: Update EXPECTED_TOOLS**

Add `"get_wan_health"` and `"compare_wan_health"` after `"set_wan_priority"`:

```python
EXPECTED_TOOLS = [
    "get_wan_status", "get_router_info",
    "get_wan_policy", "set_wan_priority",
    "get_wan_health", "compare_wan_health",
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

- [ ] **Step 6: Run the full test suite**

```bash
.venv/bin/pytest -v 2>&1 | tail -15
```

Expected: all tests pass. New total: ~127 tests (116 existing + 11 new).

- [ ] **Step 7: Commit**

```bash
git add src/server.py tests/test_server.py
git commit -m "feat: register get_wan_health and compare_wan_health MCP tools"
```
