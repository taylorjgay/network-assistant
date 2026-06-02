# Network Device Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `get_network_devices`, `label_device`, and `remove_device_label` MCP tools that build a unified view of all devices on 192.168.0.0/24 by merging ARP cache, Pi-hole client data, Deco mesh node data, and user-defined labels.

**Architecture:** New `src/tools/devices.py` module with a `DeviceInventory` class. Labels stored in `devices.json` at the project root (gitignored). Three new tools registered in `src/server.py`. The class is always instantiated (even without config) so label tools work without network access.

**Tech Stack:** Python 3.11, subprocess (arp, ping), mac-vendor-lookup, ThreadPoolExecutor, unittest.mock, pytest, existing PiholeClient and DecoClient

**Deco limitation:** `DecoClient.get_mesh_health()` returns the 3 Deco nodes by IP — it does NOT return which client devices are connected to each node (client_list crashes on current firmware). Deco enrichment only adds metadata to the 3 Deco node IPs themselves (192.168.0.100, etc.), not to other devices.

---

## File Map

- **Create:** `src/tools/devices.py` — `DeviceInventory` class, `_normalize_mac` helper
- **Create:** `devices.example.json` — committed example of labels format
- **Modify:** `requirements.txt` — add `mac-vendor-lookup`
- **Modify:** `.gitignore` — add `devices.json`
- **Modify:** `src/server.py` — register 3 new tools, instantiate `DeviceInventory`
- **Create:** `tests/test_devices.py` — all device inventory tests
- **Modify:** `tests/test_server.py` — update `EXPECTED_TOOLS` from 27 → 30

## Environment

```bash
.venv/bin/pytest tests/test_devices.py -v     # device tests only
.venv/bin/pytest -v                            # all tests
.venv/bin/pip install -r requirements.txt      # after updating requirements
```

## Key facts about existing codebase

- `PiholeClient(**vars(_cfg.pihole)).get_clients()` returns:
  `{"success": True, "clients": [{"ip": str, "hostname": str, "query_count": int, "last_query": int}]}`
  where `last_query` is a Unix timestamp (int).
- `DecoClient(**vars(_cfg.deco)).get_mesh_health()` returns:
  `{"success": True, "nodes": [{"mac": str, "ip": str, "nickname": str, "is_primary": bool, "signal_level_dbm": int, ...}]}`
- `_cfg.pihole` and `_cfg.deco` are objects whose `vars()` give kwargs to the client constructors.
- Both Pi-hole and Deco clients should be created fresh per call (no singletons — matches existing pattern in server.py).
- `arp -a` on macOS uses shortened hex MACs like `a8:9:2:ab:cd:ef` (not zero-padded). The normalize function must handle this.
- `devices.json` lives at the project root (same level as `config.json`). Path from `src/tools/devices.py`: `Path(__file__).parent.parent.parent / "devices.json"` — but the path is injected by server.py, not hardcoded in the class.

---

### Task 1: Dependencies + project scaffolding

**Files:**
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Create: `devices.example.json`
- Create: `src/tools/devices.py` (skeleton only)

- [ ] **Step 1: Add mac-vendor-lookup to requirements.txt**

Add after `pycryptodome`:
```
mac-vendor-lookup>=0.1.11
```

- [ ] **Step 2: Add devices.json to .gitignore**

Append to `.gitignore`:
```
devices.json
```

- [ ] **Step 3: Create devices.example.json**

```json
{
  "aa:bb:cc:dd:ee:ff": "Xbox Series X",
  "11:22:33:44:55:66": "Switch 2",
  "aa:bb:cc:dd:ee:00": "Raspberry Pi (Pi-hole)"
}
```

- [ ] **Step 4: Create src/tools/devices.py skeleton**

```python
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mac_vendor_lookup import MacLookup

from src.tools.deco import DecoClient
from src.tools.pihole import PiholeClient

_mac_lookup = MacLookup()


def _normalize_mac(mac: str) -> Optional[str]:
    """Normalize MAC to lowercase colon-separated. Handles shortened hex (macOS arp -a)."""
    parts = re.split(r'[:\-\.]', mac.lower().strip())
    if len(parts) != 6:
        return None
    try:
        padded = [p.zfill(2) for p in parts]
        if not all(re.match(r'^[0-9a-f]{2}$', p) for p in padded):
            return None
        return ':'.join(padded)
    except Exception:
        return None


class DeviceInventory:
    def __init__(self, labels_path: Path, cfg=None):
        self._labels_path = labels_path
        self._cfg = cfg
```

- [ ] **Step 5: Install new dependency**

```bash
.venv/bin/pip install -r requirements.txt
```

Expected: `Successfully installed mac-vendor-lookup-...`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .gitignore devices.example.json src/tools/devices.py
git commit -m "feat: scaffold network device inventory module"
```

---

### Task 2: MAC normalization + label management

**Files:**
- Modify: `src/tools/devices.py` — add `_load_labels`, `_save_labels`, `label_device`, `remove_device_label`
- Create: `tests/test_devices.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_devices.py`:

```python
import json
import pytest
from pathlib import Path
from types import SimpleNamespace

from src.tools.devices import DeviceInventory, _normalize_mac


def _cfg():
    return SimpleNamespace(
        pihole=SimpleNamespace(host="192.168.0.200", api_token="test_token"),
        deco=SimpleNamespace(host="192.168.0.100", password="test_pass"),
    )


# --- _normalize_mac ---

def test_normalize_mac_standard():
    assert _normalize_mac("AA:BB:CC:DD:EE:FF") == "aa:bb:cc:dd:ee:ff"


def test_normalize_mac_short_hex():
    # macOS arp -a uses shortened hex like a8:9:2:ab:cd:ef
    assert _normalize_mac("a8:9:2:ab:cd:ef") == "a8:09:02:ab:cd:ef"


def test_normalize_mac_already_normal():
    assert _normalize_mac("aa:bb:cc:dd:ee:ff") == "aa:bb:cc:dd:ee:ff"


def test_normalize_mac_invalid():
    assert _normalize_mac("not-a-mac") is None
    assert _normalize_mac("ZZ:BB:CC:DD:EE:FF") is None


# --- label_device ---

def test_label_device_adds_new(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    result = inv.label_device("AA:BB:CC:DD:EE:FF", "Xbox Series X")

    assert result["success"] is True
    assert result["mac"] == "aa:bb:cc:dd:ee:ff"
    assert result["label"] == "Xbox Series X"
    data = json.loads((tmp_path / "devices.json").read_text())
    assert data["aa:bb:cc:dd:ee:ff"] == "Xbox Series X"


def test_label_device_overwrites_existing(tmp_path):
    labels_file = tmp_path / "devices.json"
    labels_file.write_text(json.dumps({"aa:bb:cc:dd:ee:ff": "Old Label"}))
    inv = DeviceInventory(labels_path=labels_file, cfg=_cfg())

    result = inv.label_device("AA:BB:CC:DD:EE:FF", "New Label")

    assert result["success"] is True
    data = json.loads(labels_file.read_text())
    assert data["aa:bb:cc:dd:ee:ff"] == "New Label"


def test_label_device_invalid_mac(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    result = inv.label_device("not-a-mac", "Xbox")

    assert result["success"] is False
    assert "Invalid MAC" in result["error"]


# --- remove_device_label ---

def test_remove_device_label_success(tmp_path):
    labels_file = tmp_path / "devices.json"
    labels_file.write_text(json.dumps({"aa:bb:cc:dd:ee:ff": "Xbox Series X"}))
    inv = DeviceInventory(labels_path=labels_file, cfg=_cfg())

    result = inv.remove_device_label("AA:BB:CC:DD:EE:FF")

    assert result["success"] is True
    assert result["mac"] == "aa:bb:cc:dd:ee:ff"
    data = json.loads(labels_file.read_text())
    assert "aa:bb:cc:dd:ee:ff" not in data


def test_remove_device_label_not_found(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    result = inv.remove_device_label("AA:BB:CC:DD:EE:FF")

    assert result["success"] is False
    assert "No label found" in result["error"]


def test_remove_device_label_invalid_mac(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    result = inv.remove_device_label("not-a-mac")

    assert result["success"] is False
    assert "Invalid MAC" in result["error"]


# --- _load_labels ---

def test_load_labels_missing_file(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    assert inv._load_labels() == {}


def test_load_labels_existing_file(tmp_path):
    labels_file = tmp_path / "devices.json"
    labels_file.write_text(json.dumps({"aa:bb:cc:dd:ee:ff": "Xbox"}))
    inv = DeviceInventory(labels_path=labels_file, cfg=_cfg())
    assert inv._load_labels() == {"aa:bb:cc:dd:ee:ff": "Xbox"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_devices.py -v
```

Expected: ImportError or AttributeError — methods not yet implemented.

- [ ] **Step 3: Implement label management in src/tools/devices.py**

Add these methods inside `DeviceInventory` (after `__init__`):

```python
    def label_device(self, mac: str, label: str) -> dict:
        normalized = _normalize_mac(mac)
        if normalized is None:
            return {
                "success": False,
                "error": f"Invalid MAC address format '{mac}'",
                "suggestion": "Use format AA:BB:CC:DD:EE:FF",
            }
        labels = self._load_labels()
        labels[normalized] = label
        self._save_labels(labels)
        return {"success": True, "mac": normalized, "label": label}

    def remove_device_label(self, mac: str) -> dict:
        normalized = _normalize_mac(mac)
        if normalized is None:
            return {
                "success": False,
                "error": f"Invalid MAC address format '{mac}'",
                "suggestion": "Use format AA:BB:CC:DD:EE:FF",
            }
        labels = self._load_labels()
        if normalized not in labels:
            return {
                "success": False,
                "error": f"No label found for {normalized}",
                "suggestion": "Use label_device to add a label first",
            }
        del labels[normalized]
        self._save_labels(labels)
        return {"success": True, "mac": normalized}

    def _load_labels(self) -> dict:
        if not self._labels_path.exists():
            return {}
        try:
            return json.loads(self._labels_path.read_text())
        except Exception:
            return {}

    def _save_labels(self, labels: dict) -> None:
        self._labels_path.write_text(json.dumps(labels, indent=2))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_devices.py -v
```

Expected: all 10 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/tools/devices.py tests/test_devices.py
git commit -m "feat: add DeviceInventory label management (label_device, remove_device_label)"
```

---

### Task 3: ARP cache parsing

**Files:**
- Modify: `src/tools/devices.py` — add `_parse_arp_cache`
- Modify: `tests/test_devices.py` — append 2 tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_devices.py`:

```python
# --- _parse_arp_cache ---

from unittest.mock import patch
import subprocess


ARP_OUTPUT = """\
router.local (192.168.0.1) at a8:9:2:11:22:33 on en0 ifscope [ethernet]
? (192.168.0.50) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]
? (192.168.0.200) at (incomplete) on en0 ifscope [ethernet]
? (192.168.0.255) at ff:ff:ff:ff:ff:ff on en0 ifscope [ethernet]
"""


def test_parse_arp_cache_returns_devices(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=ARP_OUTPUT, stderr="")

    with patch("subprocess.run", return_value=mock_result):
        devices = inv._parse_arp_cache()

    ips = [d["ip"] for d in devices]
    assert "192.168.0.1" in ips
    assert "192.168.0.50" in ips
    # incomplete entries should be excluded
    assert "192.168.0.200" not in ips


def test_parse_arp_cache_empty(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    with patch("subprocess.run", return_value=mock_result):
        devices = inv._parse_arp_cache()

    assert devices == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_devices.py::test_parse_arp_cache_returns_devices tests/test_devices.py::test_parse_arp_cache_empty -v
```

Expected: FAILED — `AttributeError: 'DeviceInventory' object has no attribute '_parse_arp_cache'`

- [ ] **Step 3: Implement _parse_arp_cache in src/tools/devices.py**

Add inside `DeviceInventory` after `_save_labels`:

```python
    def _parse_arp_cache(self) -> list[dict]:
        try:
            result = subprocess.run(['arp', '-a'], capture_output=True, text=True, timeout=5)
            devices = []
            for line in result.stdout.splitlines():
                m = re.search(
                    r'\((\d+\.\d+\.\d+\.\d+)\) at ((?:[0-9a-f]{1,2}:){5}[0-9a-f]{1,2})\b',
                    line
                )
                if m:
                    devices.append({"ip": m.group(1), "mac": m.group(2)})
            return devices
        except Exception:
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_devices.py::test_parse_arp_cache_returns_devices tests/test_devices.py::test_parse_arp_cache_empty -v
```

Expected: both PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/tools/devices.py tests/test_devices.py
git commit -m "feat: add ARP cache parsing to DeviceInventory"
```

---

### Task 4: MAC vendor lookup

**Files:**
- Modify: `src/tools/devices.py` — add `_lookup_vendor`
- Modify: `tests/test_devices.py` — append 2 tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_devices.py`:

```python
# --- _lookup_vendor ---

def test_lookup_vendor_found(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())

    with patch("src.tools.devices._mac_lookup.lookup", return_value="Microsoft Corporation"):
        vendor = inv._lookup_vendor("aa:bb:cc:dd:ee:ff")

    assert vendor == "Microsoft Corporation"


def test_lookup_vendor_not_found(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())

    with patch("src.tools.devices._mac_lookup.lookup", side_effect=Exception("not found")):
        vendor = inv._lookup_vendor("aa:bb:cc:dd:ee:ff")

    assert vendor is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_devices.py::test_lookup_vendor_found tests/test_devices.py::test_lookup_vendor_not_found -v
```

Expected: FAILED — `AttributeError: 'DeviceInventory' object has no attribute '_lookup_vendor'`

- [ ] **Step 3: Implement _lookup_vendor in src/tools/devices.py**

Add inside `DeviceInventory` after `_parse_arp_cache`:

```python
    def _lookup_vendor(self, mac: str) -> Optional[str]:
        try:
            return _mac_lookup.lookup(mac)
        except Exception:
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_devices.py::test_lookup_vendor_found tests/test_devices.py::test_lookup_vendor_not_found -v
```

Expected: both PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/tools/devices.py tests/test_devices.py
git commit -m "feat: add MAC vendor lookup to DeviceInventory"
```

---

### Task 5: Pi-hole enrichment

**Files:**
- Modify: `src/tools/devices.py` — add `_enrich_pihole`
- Modify: `tests/test_devices.py` — append 2 tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_devices.py`:

```python
# --- _enrich_pihole ---

def test_enrich_pihole_adds_fields(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    devices = {
        "192.168.0.50": {
            "ip": "192.168.0.50", "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": None, "pihole_queries_today": None, "pihole_last_seen": None,
        }
    }

    with patch("src.tools.devices.PiholeClient") as MockPihole:
        MockPihole.return_value.get_clients.return_value = {
            "success": True,
            "clients": [
                {"ip": "192.168.0.50", "hostname": "xbox", "query_count": 142, "last_query": 1717330200}
            ],
        }
        inv._enrich_pihole(devices)

    assert devices["192.168.0.50"]["hostname"] == "xbox"
    assert devices["192.168.0.50"]["pihole_queries_today"] == 142
    assert devices["192.168.0.50"]["pihole_last_seen"] is not None


def test_enrich_pihole_unavailable(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    devices = {
        "192.168.0.50": {
            "ip": "192.168.0.50", "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": None, "pihole_queries_today": None, "pihole_last_seen": None,
        }
    }

    with patch("src.tools.devices.PiholeClient") as MockPihole:
        MockPihole.return_value.get_clients.return_value = {"success": False, "error": "unreachable"}
        inv._enrich_pihole(devices)

    # Fields remain None — no crash
    assert devices["192.168.0.50"]["hostname"] is None
    assert devices["192.168.0.50"]["pihole_queries_today"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_devices.py::test_enrich_pihole_adds_fields tests/test_devices.py::test_enrich_pihole_unavailable -v
```

Expected: FAILED — `AttributeError: 'DeviceInventory' object has no attribute '_enrich_pihole'`

- [ ] **Step 3: Implement _enrich_pihole in src/tools/devices.py**

Add inside `DeviceInventory` after `_lookup_vendor`:

```python
    def _enrich_pihole(self, devices: dict) -> None:
        if self._cfg is None:
            return
        try:
            result = PiholeClient(**vars(self._cfg.pihole)).get_clients()
            if not result.get("success"):
                return
            for client in result.get("clients", []):
                ip = client.get("ip", "")
                if ip not in devices:
                    continue
                hostname = client.get("hostname")
                if hostname:
                    devices[ip]["hostname"] = hostname
                devices[ip]["pihole_queries_today"] = client.get("query_count")
                last_query = client.get("last_query")
                if last_query:
                    devices[ip]["pihole_last_seen"] = datetime.fromtimestamp(
                        last_query, tz=timezone.utc
                    ).isoformat()
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_devices.py::test_enrich_pihole_adds_fields tests/test_devices.py::test_enrich_pihole_unavailable -v
```

Expected: both PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/tools/devices.py tests/test_devices.py
git commit -m "feat: add Pi-hole enrichment to DeviceInventory"
```

---

### Task 6: Deco enrichment

**Files:**
- Modify: `src/tools/devices.py` — add `_enrich_deco`
- Modify: `tests/test_devices.py` — append 2 tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_devices.py`:

```python
# --- _enrich_deco ---

def test_enrich_deco_marks_deco_nodes(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    devices = {
        "192.168.0.100": {
            "ip": "192.168.0.100", "mac": "aa:bb:cc:dd:ee:ff",
            "deco_node": None, "deco_signal_dbm": None, "connection_type": None,
        }
    }

    with patch("src.tools.devices.DecoClient") as MockDeco:
        MockDeco.return_value.get_mesh_health.return_value = {
            "success": True,
            "nodes": [
                {"ip": "192.168.0.100", "nickname": "Office", "signal_level_dbm": None, "is_primary": True}
            ],
        }
        inv._enrich_deco(devices)

    assert devices["192.168.0.100"]["deco_node"] == "Office"
    assert devices["192.168.0.100"]["connection_type"] == "deco_node"


def test_enrich_deco_unavailable(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    devices = {
        "192.168.0.100": {
            "ip": "192.168.0.100", "mac": "aa:bb:cc:dd:ee:ff",
            "deco_node": None, "deco_signal_dbm": None, "connection_type": None,
        }
    }

    with patch("src.tools.devices.DecoClient") as MockDeco:
        MockDeco.return_value.get_mesh_health.return_value = {"success": False, "error": "unreachable"}
        inv._enrich_deco(devices)

    # Fields remain None — no crash
    assert devices["192.168.0.100"]["deco_node"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_devices.py::test_enrich_deco_marks_deco_nodes tests/test_devices.py::test_enrich_deco_unavailable -v
```

Expected: FAILED — `AttributeError: 'DeviceInventory' object has no attribute '_enrich_deco'`

- [ ] **Step 3: Implement _enrich_deco in src/tools/devices.py**

Add inside `DeviceInventory` after `_enrich_pihole`:

```python
    def _enrich_deco(self, devices: dict) -> None:
        if self._cfg is None:
            return
        try:
            result = DecoClient(**vars(self._cfg.deco)).get_mesh_health()
            if not result.get("success"):
                return
            for node in result.get("nodes", []):
                ip = node.get("ip")
                if ip and ip in devices:
                    devices[ip]["deco_node"] = node.get("nickname")
                    devices[ip]["deco_signal_dbm"] = node.get("signal_level_dbm")
                    devices[ip]["connection_type"] = "deco_node"
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_devices.py::test_enrich_deco_marks_deco_nodes tests/test_devices.py::test_enrich_deco_unavailable -v
```

Expected: both PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/tools/devices.py tests/test_devices.py
git commit -m "feat: add Deco enrichment to DeviceInventory"
```

---

### Task 7: Ping sweep

**Files:**
- Modify: `src/tools/devices.py` — add `_ping_sweep`
- Modify: `tests/test_devices.py` — append 1 test

- [ ] **Step 1: Write the failing test**

Append to `tests/test_devices.py`:

```python
# --- _ping_sweep ---

def test_ping_sweep_pings_subnet(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    pinged = []

    def fake_ping(args, **kwargs):
        pinged.append(args[-1])  # last arg is the IP
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_ping):
        inv._ping_sweep()

    assert "192.168.0.1" in pinged
    assert "192.168.0.254" in pinged
    assert len(pinged) == 254
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_devices.py::test_ping_sweep_pings_subnet -v
```

Expected: FAILED — `AttributeError: 'DeviceInventory' object has no attribute '_ping_sweep'`

- [ ] **Step 3: Implement _ping_sweep in src/tools/devices.py**

Add inside `DeviceInventory` after `_enrich_deco`:

```python
    def _ping_sweep(self) -> None:
        """Ping all hosts in 192.168.0.1-254 in parallel to populate the ARP cache."""
        def ping_one(ip: str) -> None:
            subprocess.run(
                ['ping', '-c', '1', '-t', '1', ip],
                capture_output=True, timeout=3
            )

        ips = [f'192.168.0.{i}' for i in range(1, 255)]
        with ThreadPoolExecutor(max_workers=50) as executor:
            list(executor.map(ping_one, ips))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_devices.py::test_ping_sweep_pings_subnet -v
```

Expected: PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/tools/devices.py tests/test_devices.py
git commit -m "feat: add ping sweep to DeviceInventory"
```

---

### Task 8: get_network_devices assembly + integration tests

**Files:**
- Modify: `src/tools/devices.py` — add `get_network_devices`
- Modify: `tests/test_devices.py` — append 3 tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_devices.py`:

```python
# --- get_network_devices ---

def test_get_network_devices_fast_scan(tmp_path):
    labels_file = tmp_path / "devices.json"
    labels_file.write_text(json.dumps({"aa:bb:cc:dd:ee:ff": "Xbox Series X"}))
    inv = DeviceInventory(labels_path=labels_file, cfg=_cfg())

    arp_result = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout="? (192.168.0.50) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]\n",
        stderr="",
    )

    with patch("subprocess.run", return_value=arp_result), \
         patch("src.tools.devices._mac_lookup.lookup", return_value="Microsoft Corporation"), \
         patch("src.tools.devices.PiholeClient") as MockPihole, \
         patch("src.tools.devices.DecoClient") as MockDeco:

        MockPihole.return_value.get_clients.return_value = {"success": False, "error": "offline"}
        MockDeco.return_value.get_mesh_health.return_value = {"success": False, "error": "offline"}

        result = inv.get_network_devices(deep_scan=False)

    assert result["success"] is True
    assert result["deep_scan"] is False
    assert result["device_count"] == 1
    device = result["devices"][0]
    assert device["ip"] == "192.168.0.50"
    assert device["mac"] == "aa:bb:cc:dd:ee:ff"
    assert device["label"] == "Xbox Series X"
    assert device["vendor"] == "Microsoft Corporation"
    assert device["online"] is True


def test_get_network_devices_deep_scan_triggers_sweep(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())

    arp_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    ping_calls = []

    def fake_run(args, **kwargs):
        if args[0] == 'ping':
            ping_calls.append(args[-1])
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run), \
         patch("src.tools.devices.PiholeClient") as MockPihole, \
         patch("src.tools.devices.DecoClient") as MockDeco:

        MockPihole.return_value.get_clients.return_value = {"success": False}
        MockDeco.return_value.get_mesh_health.return_value = {"success": False}

        result = inv.get_network_devices(deep_scan=True)

    assert result["success"] is True
    assert result["deep_scan"] is True
    assert len(ping_calls) == 254


def test_get_network_devices_partial_enrichment(tmp_path):
    """Pi-hole and Deco both offline — still returns ARP devices with success=True."""
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())

    arp_result = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout="? (192.168.0.50) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]\n",
        stderr="",
    )

    with patch("subprocess.run", return_value=arp_result), \
         patch("src.tools.devices._mac_lookup.lookup", side_effect=Exception("no vendor")), \
         patch("src.tools.devices.PiholeClient") as MockPihole, \
         patch("src.tools.devices.DecoClient") as MockDeco:

        MockPihole.return_value.get_clients.return_value = {"success": False}
        MockDeco.return_value.get_mesh_health.return_value = {"success": False}

        result = inv.get_network_devices()

    assert result["success"] is True
    device = result["devices"][0]
    assert device["hostname"] is None
    assert device["vendor"] is None
    assert device["pihole_queries_today"] is None
    assert device["deco_node"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_devices.py::test_get_network_devices_fast_scan tests/test_devices.py::test_get_network_devices_deep_scan_triggers_sweep tests/test_devices.py::test_get_network_devices_partial_enrichment -v
```

Expected: all 3 FAILED — `AttributeError: 'DeviceInventory' object has no attribute 'get_network_devices'`

- [ ] **Step 3: Implement get_network_devices in src/tools/devices.py**

Add inside `DeviceInventory` after `__init__` (before label methods):

```python
    def get_network_devices(self, deep_scan: bool = False) -> dict:
        try:
            if deep_scan:
                self._ping_sweep()

            raw_devices = self._parse_arp_cache()
            labels = self._load_labels()

            devices: dict[str, dict] = {}
            for d in raw_devices:
                mac = _normalize_mac(d["mac"]) or d["mac"]
                devices[d["ip"]] = {
                    "ip": d["ip"],
                    "mac": mac,
                    "label": labels.get(mac),
                    "hostname": None,
                    "vendor": self._lookup_vendor(mac),
                    "online": True,
                    "pihole_queries_today": None,
                    "pihole_last_seen": None,
                    "deco_node": None,
                    "deco_signal_dbm": None,
                    "connection_type": None,
                }

            self._enrich_pihole(devices)
            self._enrich_deco(devices)

            sorted_devices = sorted(
                devices.values(),
                key=lambda d: [int(x) for x in d["ip"].split(".")],
            )
            return {
                "success": True,
                "deep_scan": deep_scan,
                "device_count": len(sorted_devices),
                "devices": sorted_devices,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "suggestion": "Check that 'arp' is available on PATH",
            }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_devices.py -v
```

Expected: all tests PASSED. Count: ~22 tests.

- [ ] **Step 5: Commit**

```bash
git add src/tools/devices.py tests/test_devices.py
git commit -m "feat: add get_network_devices to DeviceInventory"
```

---

### Task 9: Register tools in server.py + update test_server.py

**Files:**
- Modify: `src/server.py` — import DeviceInventory, instantiate, register 3 tools
- Modify: `tests/test_server.py` — update EXPECTED_TOOLS (27 → 30)

- [ ] **Step 1: Read the top of src/server.py to find import and instantiation section**

Confirm the existing pattern:
```python
from src.tools.er605 import ER605Client
from src.tools.deco import DecoClient
from src.tools.pihole import PiholeClient
...
_er605 = ER605Client(**vars(_cfg.er605)) if _cfg else None
```

- [ ] **Step 2: Add DeviceInventory import and instantiation to src/server.py**

Add to the import block (after `from src.tools.pihole import PiholeClient`):
```python
from src.tools.devices import DeviceInventory
```

Add to the instantiation block (after `_deco = ...`):
```python
_devices_labels_path = Path(__file__).parent.parent / "devices.json"
_devices = DeviceInventory(labels_path=_devices_labels_path, cfg=_cfg)
```

- [ ] **Step 3: Register the three tools in src/server.py**

Add after `get_port_forwards` tool (or at the end of the ER605 tool block, before `get_connected_clients`):

```python
@mcp.tool()
def get_network_devices(deep_scan: bool = False) -> dict:
    """Get all devices on 192.168.0.x: IP, MAC, label, hostname, vendor, Pi-hole stats, Deco node info. deep_scan=True pings all 254 hosts first (~15s) to find idle devices."""
    return _devices.get_network_devices(deep_scan=deep_scan)


@mcp.tool()
def label_device(mac: str, label: str) -> dict:
    """Assign a friendly name to a device by MAC address (e.g. 'AA:BB:CC:DD:EE:FF', 'Xbox Series X'). Labels persist in devices.json."""
    return _devices.label_device(mac, label)


@mcp.tool()
def remove_device_label(mac: str) -> dict:
    """Remove a device label by MAC address. Use get_network_devices to find MACs."""
    return _devices.remove_device_label(mac)
```

- [ ] **Step 4: Update EXPECTED_TOOLS in tests/test_server.py**

Replace the existing `EXPECTED_TOOLS` list with:

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
    "remove_domain", "set_blocking", "update_gravity",
    "test_dns_resolution", "ping_host", "traceroute_host", "run_speedtest",
]
```

- [ ] **Step 5: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass. New total: ~110 tests (88 existing + ~22 new device tests).

- [ ] **Step 6: Commit**

```bash
git add src/server.py tests/test_server.py
git commit -m "feat: register get_network_devices, label_device, remove_device_label MCP tools"
```
