# NetworkAssistant Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python MCP server with 9 read-only diagnostic tools that give Claude access to a home network's ER605 router, Deco X55 mesh, Pi-hole, and standard network utilities.

**Architecture:** FastMCP server (Python) runs as a Claude Code subprocess. Each device has its own client class in `src/tools/`. The MCP server in `src/server.py` instantiates clients from `config.json` and registers their methods as tools.

**Tech Stack:** Python 3.11+, `mcp[cli]` (FastMCP), `httpx`, `pycryptodome` (Deco AES auth), `speedtest-cli`, `pytest`, `respx` (HTTP mocking)

---

## File Map

| File | Responsibility |
|---|---|
| `src/server.py` | FastMCP entry point; instantiates clients; registers all tools |
| `src/config.py` | Loads and validates `config.json`; typed dataclasses |
| `src/tools/diagnostics.py` | `ping_host`, `traceroute_host`, `run_speedtest`, `test_dns_resolution` |
| `src/tools/pihole.py` | `PiholeClient` — Pi-hole v5/v6 REST API |
| `src/tools/er605.py` | `ER605Client` — session-based reverse-engineered HTTP API |
| `src/tools/deco.py` | `DecoClient` — AES-encrypted local API |
| `tests/conftest.py` | Shared fixtures (sample config, mock responses) |
| `tests/test_config.py` | Config loading validation |
| `tests/test_diagnostics.py` | Diagnostics with mocked subprocess/speedtest |
| `tests/test_pihole.py` | Pi-hole client with mocked httpx |
| `tests/test_er605.py` | ER605 client with mocked httpx |
| `tests/test_deco.py` | Deco client with mocked httpx + crypto |
| `tests/test_server.py` | MCP server tool registration |
| `config.example.json` | Committed template with placeholder values |
| `.gitignore` | Excludes `config.json`, `.superpowers/`, `__pycache__` |
| `pytest.ini` | Sets `asyncio_mode = auto` |
| `requirements.txt` | Pinned dependencies |
| `.claude/mcp_settings.json` | Registers server with Claude Code |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `config.example.json`
- Create: `src/__init__.py`, `src/tools/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/tools tests .claude
touch src/__init__.py src/tools/__init__.py tests/__init__.py
```

- [ ] **Step 2: Create `.gitignore`**

```
config.json
.superpowers/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
dist/
.venv/
```

- [ ] **Step 3: Create `requirements.txt`**

```
mcp[cli]>=1.0.0
httpx>=0.27.0
pycryptodome>=3.20.0
speedtest-cli>=2.1.3
pytest>=8.0.0
pytest-asyncio>=0.23.0
respx>=0.21.0
```

- [ ] **Step 4: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 5: Create `config.example.json`**

```json
{
  "er605": {
    "host": "192.168.0.1",
    "username": "admin",
    "password": "your-router-password"
  },
  "deco": {
    "host": "192.168.0.1",
    "password": "your-deco-app-password"
  },
  "pihole": {
    "host": "192.168.0.x",
    "api_token": "your-pihole-api-token"
  }
}
```

- [ ] **Step 6: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without error.

- [ ] **Step 7: Commit**

```bash
git init
git add .gitignore requirements.txt pytest.ini config.example.json src/__init__.py src/tools/__init__.py tests/__init__.py
git commit -m "chore: project scaffolding"
```

---

## Task 2: Config Loading

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/conftest.py`:
```python
import json
import pytest
from pathlib import Path


@pytest.fixture
def sample_config_data():
    return {
        "er605": {"host": "192.168.0.1", "username": "admin", "password": "secret"},
        "deco": {"host": "192.168.0.1", "password": "decopass"},
        "pihole": {"host": "192.168.0.10", "api_token": "abc123"},
    }


@pytest.fixture
def config_file(tmp_path, sample_config_data):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(sample_config_data))
    return p
```

Create `tests/test_config.py`:
```python
import json
import pytest
from src.config import load_config, Config, ER605Config, DecoConfig, PiholeConfig


def test_load_config_returns_typed_config(config_file):
    cfg = load_config(config_file)
    assert isinstance(cfg, Config)
    assert isinstance(cfg.er605, ER605Config)
    assert isinstance(cfg.deco, DecoConfig)
    assert isinstance(cfg.pihole, PiholeConfig)


def test_load_config_er605_fields(config_file):
    cfg = load_config(config_file)
    assert cfg.er605.host == "192.168.0.1"
    assert cfg.er605.username == "admin"
    assert cfg.er605.password == "secret"


def test_load_config_deco_fields(config_file):
    cfg = load_config(config_file)
    assert cfg.deco.host == "192.168.0.1"
    assert cfg.deco.password == "decopass"


def test_load_config_pihole_fields(config_file):
    cfg = load_config(config_file)
    assert cfg.pihole.host == "192.168.0.10"
    assert cfg.pihole.api_token == "abc123"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.json")


def test_load_config_missing_er605_key_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"deco": {"host": "x", "password": "y"}, "pihole": {"host": "z", "api_token": "w"}}))
    with pytest.raises(KeyError):
        load_config(p)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.config'`

- [ ] **Step 3: Implement `src/config.py`**

```python
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ER605Config:
    host: str
    username: str
    password: str


@dataclass
class DecoConfig:
    host: str
    password: str


@dataclass
class PiholeConfig:
    host: str
    api_token: str


@dataclass
class Config:
    er605: ER605Config
    deco: DecoConfig
    pihole: PiholeConfig


def load_config(path=None) -> Config:
    if path is None:
        path = Path(__file__).parent.parent / "config.json"
    with open(path) as f:
        data = json.load(f)
    return Config(
        er605=ER605Config(**data["er605"]),
        deco=DecoConfig(**data["deco"]),
        pihole=PiholeConfig(**data["pihole"]),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py tests/conftest.py
git commit -m "feat: config loading with typed dataclasses"
```

---

## Task 3: MCP Server Skeleton

**Files:**
- Create: `src/server.py`
- Create: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_server.py`:
```python
import importlib
import src.server as server_module


def test_server_has_name():
    assert server_module.mcp.name == "NetworkAssistant"


def test_server_module_imports_without_error():
    # Verifies no import-time side effects crash on missing config.json
    assert server_module is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_server.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.server'`

- [ ] **Step 3: Implement `src/server.py`**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("NetworkAssistant")


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_server.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Verify server starts manually**

```bash
echo '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}},"id":1}' | python src/server.py
```

Expected: JSON response containing `"result"` with `serverInfo.name = "NetworkAssistant"`.

- [ ] **Step 6: Commit**

```bash
git add src/server.py tests/test_server.py
git commit -m "feat: MCP server skeleton"
```

---

## Task 4: Network Diagnostics Tools

**Files:**
- Create: `src/tools/diagnostics.py`
- Create: `tests/test_diagnostics.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_diagnostics.py`:
```python
import subprocess
from unittest.mock import patch, MagicMock
import pytest
from src.tools.diagnostics import ping_host, traceroute_host, test_dns_resolution


def test_ping_host_success():
    mock_output = (
        "PING 8.8.8.8 (8.8.8.8): 56 data bytes\n"
        "64 bytes from 8.8.8.8: icmp_seq=0 ttl=118 time=12.3 ms\n"
        "--- 8.8.8.8 ping statistics ---\n"
        "4 packets transmitted, 4 packets received, 0.0% packet loss\n"
        "round-trip min/avg/max/stddev = 11.2/12.3/13.4/0.8 ms\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
        result = ping_host("8.8.8.8", count=4)
    assert result["success"] is True
    assert result["host"] == "8.8.8.8"
    assert result["packet_loss_pct"] == 0.0
    assert result["avg_ms"] == 12.3


def test_ping_host_unreachable():
    mock_output = (
        "--- 10.0.0.99 ping statistics ---\n"
        "4 packets transmitted, 0 packets received, 100.0% packet loss\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=2, stdout=mock_output, stderr="")
        result = ping_host("10.0.0.99", count=4)
    assert result["success"] is True  # tool succeeded, host is unreachable
    assert result["packet_loss_pct"] == 100.0


def test_ping_host_timeout():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ping", timeout=10)
        result = ping_host("10.0.0.99", count=4)
    assert result["success"] is False
    assert "timed out" in result["error"].lower()


def test_traceroute_host_success():
    mock_output = (
        "traceroute to 8.8.8.8, 30 hops max\n"
        " 1  192.168.0.1  1.234 ms\n"
        " 2  10.0.0.1  5.678 ms\n"
        " 3  8.8.8.8  12.345 ms\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
        result = traceroute_host("8.8.8.8")
    assert result["success"] is True
    assert result["host"] == "8.8.8.8"
    assert len(result["hops"]) == 3
    assert result["hops"][0]["ip"] == "192.168.0.1"


def test_test_dns_resolution_success():
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(2, 1, 6, "", ("142.250.80.46", 0))]
        result = test_dns_resolution("google.com")
    assert result["success"] is True
    assert "142.250.80.46" in result["addresses"]
    assert result["hostname"] == "google.com"


def test_test_dns_resolution_failure():
    import socket
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.side_effect = socket.gaierror("Name or service not known")
        result = test_dns_resolution("doesnotexist.invalid")
    assert result["success"] is False
    assert "suggestion" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_diagnostics.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.tools.diagnostics'`

- [ ] **Step 3: Implement `src/tools/diagnostics.py`**

```python
import re
import socket
import subprocess
import time


def ping_host(host: str, count: int = 4) -> dict:
    """Ping a host, return latency and packet loss."""
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), host],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout
        loss_match = re.search(r"([\d.]+)% packet loss", output)
        packet_loss = float(loss_match.group(1)) if loss_match else 100.0
        avg_ms = None
        rtt_match = re.search(r"min/avg/max/[^\s]+ = [\d.]+/([\d.]+)/", output)
        if rtt_match:
            avg_ms = float(rtt_match.group(1))
        return {
            "success": True,
            "host": host,
            "packets_sent": count,
            "packet_loss_pct": packet_loss,
            "avg_ms": avg_ms,
            "reachable": packet_loss < 100.0,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "host": host, "error": "ping timed out after 15s",
                "suggestion": "Host may be unreachable or firewall is blocking ICMP"}
    except Exception as e:
        return {"success": False, "host": host, "error": str(e), "suggestion": "Check that 'ping' is available on PATH"}


def traceroute_host(host: str) -> dict:
    """Traceroute to a host, returning each hop."""
    try:
        result = subprocess.run(
            ["traceroute", "-n", host],
            capture_output=True, text=True, timeout=60
        )
        hops = []
        for line in result.stdout.splitlines():
            m = re.match(r"\s*(\d+)\s+([\d.]+|\*)\s+([\d.]+)\s+ms", line)
            if m:
                hops.append({"hop": int(m.group(1)), "ip": m.group(2), "ms": float(m.group(3))})
        return {"success": True, "host": host, "hops": hops, "raw": result.stdout}
    except subprocess.TimeoutExpired:
        return {"success": False, "host": host, "error": "traceroute timed out after 60s", "suggestion": ""}
    except Exception as e:
        return {"success": False, "host": host, "error": str(e), "suggestion": "Check that 'traceroute' is available on PATH"}


def test_dns_resolution(hostname: str, dns_server: str = None) -> dict:
    """Resolve a hostname and return the addresses."""
    start = time.monotonic()
    try:
        if dns_server:
            # Use dig for custom DNS server
            result = subprocess.run(
                ["dig", f"@{dns_server}", hostname, "+short"],
                capture_output=True, text=True, timeout=10
            )
            addresses = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            elapsed_ms = (time.monotonic() - start) * 1000
            return {"success": True, "hostname": hostname, "dns_server": dns_server,
                    "addresses": addresses, "elapsed_ms": round(elapsed_ms, 1)}
        else:
            infos = socket.getaddrinfo(hostname, None)
            addresses = list({info[4][0] for info in infos})
            elapsed_ms = (time.monotonic() - start) * 1000
            return {"success": True, "hostname": hostname, "dns_server": "system default",
                    "addresses": addresses, "elapsed_ms": round(elapsed_ms, 1)}
    except socket.gaierror as e:
        return {"success": False, "hostname": hostname, "error": str(e),
                "suggestion": "DNS resolution failed — Pi-hole may be blocking this domain or DNS is misconfigured"}
    except Exception as e:
        return {"success": False, "hostname": hostname, "error": str(e), "suggestion": ""}


def run_speedtest() -> dict:
    """Run an internet speed test."""
    try:
        import speedtest
        st = speedtest.Speedtest(secure=True)
        st.get_best_server()
        download_bps = st.download()
        upload_bps = st.upload()
        results = st.results.dict()
        return {
            "success": True,
            "download_mbps": round(download_bps / 1_000_000, 1),
            "upload_mbps": round(upload_bps / 1_000_000, 1),
            "ping_ms": results.get("ping"),
            "server": results.get("server", {}).get("name"),
            "server_location": f"{results.get('server', {}).get('city')}, {results.get('server', {}).get('country')}",
        }
    except Exception as e:
        return {"success": False, "error": str(e),
                "suggestion": "Check internet connectivity; speedtest-cli must be installed"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_diagnostics.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tools/diagnostics.py tests/test_diagnostics.py
git commit -m "feat: ping, traceroute, DNS, and speedtest diagnostic tools"
```

---

## Task 5: Pi-hole Client

**Files:**
- Create: `src/tools/pihole.py`
- Create: `tests/test_pihole.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pihole.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pihole.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.tools.pihole'`

- [ ] **Step 3: Implement `src/tools/pihole.py`**

```python
import httpx


class PiholeClient:
    def __init__(self, host: str, api_token: str):
        self.host = host
        self.api_token = api_token
        self._base = f"http://{host}/admin/api.php"

    def get_pihole_stats(self) -> dict:
        """Get Pi-hole summary statistics."""
        url = self._base
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(url, params={"summaryRaw": "", "auth": self.api_token})
            resp.raise_for_status()
            data = resp.json()
            if "FTLnotrunning" in data:
                return {"success": False, "error": "Pi-hole FTL is not running",
                        "suggestion": "Restart Pi-hole: sudo pihole restartdns",
                        "attempted": url}
            return {
                "success": True,
                "queries_today": data.get("dns_queries_today", 0),
                "blocked_today": data.get("ads_blocked_today", 0),
                "block_pct": round(data.get("ads_percentage_today", 0.0), 1),
                "domains_blocked": data.get("domains_being_blocked", 0),
                "enabled": data.get("status") == "enabled",
            }
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"HTTP {e.response.status_code}",
                    "suggestion": "Check Pi-hole host in config.json and that the admin interface is reachable",
                    "attempted": url}
        except httpx.ConnectError:
            return {"success": False, "error": "Connection refused",
                    "suggestion": f"Cannot reach Pi-hole at {self.host} — verify IP in config.json",
                    "attempted": url}
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def test_dns_resolution(self, hostname: str) -> dict:
        """Check if Pi-hole would block a hostname by querying its recent logs."""
        url = self._base
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(url, params={"recentBlocked": "", "auth": self.api_token})
            resp.raise_for_status()
            recent_blocked = resp.text.strip()
            return {
                "success": True,
                "hostname": hostname,
                "most_recently_blocked": recent_blocked,
                "is_recently_blocked": hostname in recent_blocked,
            }
        except Exception as e:
            return {"success": False, "hostname": hostname, "error": str(e),
                    "suggestion": "Check Pi-hole connectivity", "attempted": url}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pihole.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tools/pihole.py tests/test_pihole.py
git commit -m "feat: Pi-hole stats and DNS client"
```

---

## Task 6: ER605 Client

**Files:**
- Create: `src/tools/er605.py`
- Create: `tests/test_er605.py`

> **Note:** The ER605 standalone API is reverse-engineered. These endpoints match the documented TP-Link business router pattern but must be verified against your firmware. If responses differ, capture browser dev tools traffic from the router's web UI (`http://[router-ip]`) to see actual endpoint formats. The `get_router_info` tool reports the firmware version to help debug discrepancies.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_er605.py`:
```python
import hashlib
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
    # Login response
    respx.post("http://192.168.0.1").mock(return_value=httpx.Response(200, json={
        "error_code": 0,
        "login": {"stok": "abc123"}
    }))
    # WAN status response
    respx.post("http://192.168.0.1/stok=abc123/ds").mock(return_value=httpx.Response(200, json={
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
    result = client.get_wan_status()
    assert result["success"] is True
    assert result["wan1"]["link_status"] == "up"
    assert result["wan1"]["ip"] == "1.2.3.4"


@respx.mock
def test_get_wan_status_auth_failure(client):
    respx.post("http://192.168.0.1").mock(return_value=httpx.Response(200, json={
        "error_code": -22001,
        "error_msg": "invalid username or password"
    }))
    result = client.get_wan_status()
    assert result["success"] is False
    assert "auth" in result["error"].lower() or "password" in result["suggestion"].lower()


@respx.mock
def test_get_router_info_success(client):
    respx.post("http://192.168.0.1").mock(return_value=httpx.Response(200, json={
        "error_code": 0,
        "login": {"stok": "abc123"}
    }))
    respx.post("http://192.168.0.1/stok=abc123/ds").mock(return_value=httpx.Response(200, json={
        "error_code": 0,
        "system": {
            "name": {
                "model": "TL-ER605",
                "firmware": "2.0.0 Build 20221208",
                "uptime": 172800,
            }
        }
    }))
    result = client.get_router_info()
    assert result["success"] is True
    assert result["model"] == "TL-ER605"
    assert "firmware" in result


@respx.mock
def test_connection_refused(client):
    respx.post("http://192.168.0.1").mock(side_effect=httpx.ConnectError("refused"))
    result = client.get_wan_status()
    assert result["success"] is False
    assert "192.168.0.1" in result["attempted"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_er605.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.tools.er605'`

- [ ] **Step 3: Implement `src/tools/er605.py`**

```python
import hashlib
import httpx


class ER605Client:
    def __init__(self, host: str, username: str, password: str):
        self.host = host
        self.username = username
        self.password = password
        self._base = f"http://{host}"

    def _md5(self, s: str) -> str:
        return hashlib.md5(s.encode()).hexdigest().upper()

    def _login(self, client: httpx.Client) -> str | None:
        """Authenticate and return stok session token, or None on failure."""
        resp = client.post(self._base, json={
            "method": "do",
            "login": {"username": self.username, "password": self._md5(self.password)}
        })
        data = resp.json()
        if data.get("error_code") != 0:
            return None
        return data.get("login", {}).get("stok")

    def _post(self, client: httpx.Client, stok: str, payload: dict) -> dict:
        resp = client.post(f"{self._base}/stok={stok}/ds", json=payload)
        return resp.json()

    def get_wan_status(self) -> dict:
        """Get WAN1/WAN2 link status, IPs, and failover state."""
        url = f"{self._base}"
        try:
            with httpx.Client(timeout=10) as client:
                stok = self._login(client)
                if stok is None:
                    return {"success": False, "error": "ER605 authentication failed",
                            "suggestion": "Check er605.username and er605.password in config.json",
                            "attempted": url}
                data = self._post(client, stok, {"method": "get", "network": {"name": "wan_status"}})
            if data.get("error_code") != 0:
                return {"success": False, "error": f"ER605 error_code {data.get('error_code')}",
                        "suggestion": "WAN status endpoint may differ on this firmware version",
                        "attempted": url, "raw": data}
            wan = data.get("network", {}).get("wan_status", {})
            return {
                "success": True,
                "wan1": {
                    "link_status": wan.get("link_status"),
                    "ip": wan.get("ip"),
                    "proto": wan.get("proto"),
                    "uptime_seconds": wan.get("uptime"),
                },
                "active_wan": "wan1",
            }
        except httpx.ConnectError:
            return {"success": False, "error": "Cannot connect to ER605",
                    "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                    "attempted": url}
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def get_router_info(self) -> dict:
        """Get ER605 firmware version, model, and uptime."""
        url = self._base
        try:
            with httpx.Client(timeout=10) as client:
                stok = self._login(client)
                if stok is None:
                    return {"success": False, "error": "ER605 authentication failed",
                            "suggestion": "Check er605.username and er605.password in config.json",
                            "attempted": url}
                data = self._post(client, stok, {"method": "get", "system": {"name": ["name", "status"]}})
            if data.get("error_code") != 0:
                return {"success": False, "error": f"ER605 error_code {data.get('error_code')}",
                        "suggestion": "System info endpoint may differ on this firmware version",
                        "attempted": url, "raw": data}
            info = data.get("system", {}).get("name", {})
            return {
                "success": True,
                "model": info.get("model"),
                "firmware": info.get("firmware"),
                "uptime_seconds": info.get("uptime"),
            }
        except httpx.ConnectError:
            return {"success": False, "error": "Cannot connect to ER605",
                    "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                    "attempted": url}
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_er605.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tools/er605.py tests/test_er605.py
git commit -m "feat: ER605 WAN status and system info client"
```

---

## Task 7: Deco Client

**Files:**
- Create: `src/tools/deco.py`
- Create: `tests/test_deco.py`

> **Protocol note:** The Deco local API uses AES-CBC encryption with an RSA key exchange. All request/response bodies are encrypted after the initial handshake. This matches the protocol used by the Home Assistant `tplink_deco` integration. The primary Deco node (wired to ER605) is the entry point for all mesh data.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deco.py`:
```python
import base64
import json
import pytest
import respx
import httpx
from unittest.mock import patch, MagicMock
from src.tools.deco import DecoClient


@pytest.fixture
def client():
    return DecoClient(host="192.168.0.1", password="decopass")


def make_mock_encrypted_response(payload: dict) -> str:
    """Return a base64-encoded fake encrypted response for testing."""
    return base64.b64encode(json.dumps(payload).encode()).decode()


@respx.mock
def test_get_connected_clients_success(client):
    client_list_payload = {
        "error_code": 0,
        "result": {
            "client_list": [
                {
                    "mac": "AA:BB:CC:DD:EE:FF",
                    "ip": "192.168.68.100",
                    "name": "Taylors-iPhone",
                    "device_type": "phone",
                    "up_speed": 0,
                    "down_speed": 102400,
                    "owner_id": "",
                    "guest": False,
                    "type": "wireless",
                    "wire_type": "wifi5",
                    "belong_to": "AA:11:22:33:44:55",
                }
            ]
        }
    }
    with patch.object(client, "_authenticated_request", return_value=client_list_payload):
        result = client.get_connected_clients()
    assert result["success"] is True
    assert len(result["clients"]) == 1
    assert result["clients"][0]["hostname"] == "Taylors-iPhone"
    assert result["clients"][0]["mac"] == "AA:BB:CC:DD:EE:FF"
    assert result["clients"][0]["ip"] == "192.168.68.100"


@respx.mock
def test_get_mesh_health_success(client):
    device_list_payload = {
        "error_code": 0,
        "result": {
            "device_list": [
                {
                    "mac": "AA:11:22:33:44:55",
                    "device_ip": "192.168.0.1",
                    "inet_status": "online",
                    "master": True,
                    "bssid_5g": "AA:11:22:33:44:56",
                    "connection_type": "wired",
                    "signal_level": {"band5_0": 0},
                },
                {
                    "mac": "BB:11:22:33:44:55",
                    "device_ip": "192.168.0.2",
                    "inet_status": "online",
                    "master": False,
                    "connection_type": "wired",
                    "signal_level": {"band5_0": 0},
                },
                {
                    "mac": "CC:11:22:33:44:55",
                    "device_ip": "192.168.0.3",
                    "inet_status": "online",
                    "master": False,
                    "connection_type": "wireless",
                    "signal_level": {"band5_0": -65},
                },
            ]
        }
    }
    with patch.object(client, "_authenticated_request", return_value=device_list_payload):
        result = client.get_mesh_health()
    assert result["success"] is True
    assert len(result["nodes"]) == 3
    wireless_node = next(n for n in result["nodes"] if n["backhaul"] == "wireless")
    assert wireless_node["signal_level_dbm"] == -65


def test_get_connected_clients_auth_failure(client):
    with patch.object(client, "_authenticated_request", side_effect=Exception("auth failed")):
        result = client.get_connected_clients()
    assert result["success"] is False
    assert "suggestion" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_deco.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.tools.deco'`

- [ ] **Step 3: Implement `src/tools/deco.py`**

```python
import base64
import hashlib
import json
import os
import time

import httpx
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad


class DecoClient:
    """
    Client for the TP-Link Deco local API.
    Uses RSA key exchange + AES-CBC for all communication.
    Entry point is the primary Deco node (wired to ER605).
    """

    def __init__(self, host: str, password: str):
        self.host = host
        self.password = password
        self._base = f"http://{host}/cgi-bin/luci/;stok=/ds"
        self._stok = None
        self._aes_key = None
        self._aes_iv = None

    def _md5(self, s: str) -> str:
        return hashlib.md5(s.encode()).hexdigest()

    def _aes_encrypt(self, plaintext: str) -> str:
        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._aes_iv)
        encrypted = cipher.encrypt(pad(plaintext.encode(), AES.block_size))
        return base64.b64encode(encrypted).decode()

    def _aes_decrypt(self, ciphertext: str) -> str:
        data = base64.b64decode(ciphertext)
        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._aes_iv)
        return unpad(cipher.decrypt(data), AES.block_size).decode()

    def _get_encryption_params(self, client: httpx.Client) -> tuple[bytes, bytes, str]:
        """Phase 1: get RSA public key from device, return (rsa_key_n, rsa_key_e, seq)."""
        payload = {"params": {"operation": "read"}}
        resp = client.post(self._base, json={"method": "do", "login": payload})
        data = resp.json()
        # Response contains RSA public key components for encrypting our AES key
        keys = data.get("result", {})
        n = int(keys.get("key", {}).get("n", "0"), 16)
        e = int(keys.get("key", {}).get("e", "0"), 16)
        seq = keys.get("seq", "0")
        return n, e, seq

    def _authenticate(self, client: httpx.Client) -> bool:
        """Full auth flow: RSA key exchange then login with AES-encrypted credentials."""
        # Generate AES session key
        self._aes_key = os.urandom(16)
        self._aes_iv = os.urandom(16)

        # Get device RSA public key
        try:
            n, e, seq = self._get_encryption_params(client)
            if n == 0:
                # Simpler auth fallback for some firmware versions
                resp = client.post(self._base, json={
                    "method": "do",
                    "login": {"password": self._md5(self.password)}
                })
                data = resp.json()
                if data.get("error_code") == 0:
                    self._stok = data.get("stok", "")
                    return True
                return False

            rsa_key = RSA.construct((n, e))
            cipher_rsa = PKCS1_OAEP.new(rsa_key)
            encrypted_aes = base64.b64encode(
                cipher_rsa.encrypt(self._aes_key + self._aes_iv)
            ).decode()
        except Exception:
            return False

        # Send encrypted login
        login_body = json.dumps({"method": "do", "login": {
            "password": self._md5(self.password)
        }})
        encrypted_body = self._aes_encrypt(login_body)
        resp = client.post(self._base, json={"params": encrypted_body, "sign": encrypted_aes, "seq": seq})
        try:
            raw = resp.json()
            decrypted = self._aes_decrypt(raw.get("result", ""))
            data = json.loads(decrypted)
            if data.get("error_code") == 0:
                self._stok = data.get("stok", "")
                return True
        except Exception:
            pass
        return False

    def _authenticated_request(self, payload: dict) -> dict:
        """Send an encrypted authenticated request and return decrypted response."""
        with httpx.Client(timeout=15) as client:
            if not self._stok:
                if not self._authenticate(client):
                    raise Exception("Deco authentication failed — check deco.password in config.json")

            url = f"http://{self.host}/cgi-bin/luci/;stok={self._stok}/ds"
            if self._aes_key:
                body = json.dumps(payload)
                encrypted = self._aes_encrypt(body)
                resp = client.post(url, json={"params": encrypted})
                raw = resp.json()
                decrypted = self._aes_decrypt(raw.get("result", ""))
                return json.loads(decrypted)
            else:
                resp = client.post(url, json=payload)
                return resp.json()

    def get_connected_clients(self) -> dict:
        """Get all clients connected to the mesh with their Deco node assignment."""
        try:
            data = self._authenticated_request({
                "method": "get",
                "client_list": {"name": ["client_list"]}
            })
            clients_raw = data.get("result", {}).get("client_list", [])
            clients = [{
                "hostname": c.get("name", c.get("mac", "unknown")),
                "mac": c.get("mac"),
                "ip": c.get("ip"),
                "deco_node_mac": c.get("belong_to"),
                "connection": c.get("type"),
                "band": c.get("wire_type"),
            } for c in clients_raw]
            return {"success": True, "clients": clients, "count": len(clients)}
        except Exception as e:
            return {"success": False, "error": str(e),
                    "suggestion": "Check deco.host and deco.password in config.json"}

    def get_mesh_health(self) -> dict:
        """Get status of all Deco nodes including backhaul type and signal strength."""
        try:
            data = self._authenticated_request({
                "method": "get",
                "device_list": {"name": ["device_list"]}
            })
            nodes_raw = data.get("result", {}).get("device_list", [])
            nodes = [{
                "mac": n.get("mac"),
                "ip": n.get("device_ip"),
                "status": n.get("inet_status"),
                "is_primary": n.get("master", False),
                "backhaul": n.get("connection_type"),
                "signal_level_dbm": n.get("signal_level", {}).get("band5_0"),
            } for n in nodes_raw]
            return {"success": True, "nodes": nodes, "node_count": len(nodes)}
        except Exception as e:
            return {"success": False, "error": str(e),
                    "suggestion": "Check deco.host and deco.password in config.json"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_deco.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tools/deco.py tests/test_deco.py
git commit -m "feat: Deco mesh client with AES-encrypted local API"
```

---

## Task 8: Wire All Tools Into MCP Server

**Files:**
- Modify: `src/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write the failing test for tool registration**

Replace `tests/test_server.py`:
```python
import src.server as server_module

EXPECTED_TOOLS = [
    "get_wan_status",
    "get_router_info",
    "get_connected_clients",
    "get_mesh_health",
    "get_pihole_stats",
    "test_dns_resolution",
    "ping_host",
    "traceroute_host",
    "run_speedtest",
]


def test_server_has_name():
    assert server_module.mcp.name == "NetworkAssistant"


def test_all_tools_are_callable():
    for name in EXPECTED_TOOLS:
        assert callable(getattr(server_module, name, None)), f"Tool '{name}' not found in server module"
```

- [ ] **Step 2: Run tests to verify the tool registration test fails**

```bash
pytest tests/test_server.py::test_all_tools_registered -v
```

Expected: FAIL — tool list is empty.

- [ ] **Step 3: Implement tool registration in `src/server.py`**

```python
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.config import load_config
from src.tools.diagnostics import (
    ping_host as _ping_host,
    traceroute_host as _traceroute_host,
    run_speedtest as _run_speedtest,
    test_dns_resolution as _test_dns_resolution,
)
from src.tools.er605 import ER605Client
from src.tools.deco import DecoClient
from src.tools.pihole import PiholeClient

mcp = FastMCP("NetworkAssistant")

_config_path = Path(__file__).parent.parent / "config.json"
_cfg = load_config(_config_path) if _config_path.exists() else None

_er605 = ER605Client(**vars(_cfg.er605)) if _cfg else None
_deco = DecoClient(**vars(_cfg.deco)) if _cfg else None
_pihole = PiholeClient(**vars(_cfg.pihole)) if _cfg else None

_NO_CONFIG = {"success": False, "error": "config.json not found",
              "suggestion": "Copy config.example.json to config.json and fill in your device details"}


@mcp.tool()
def get_wan_status() -> dict:
    """Get ER605 WAN status: active interface, public IP, uptime, failover state."""
    return _er605.get_wan_status() if _er605 else _NO_CONFIG


@mcp.tool()
def get_router_info() -> dict:
    """Get ER605 model, firmware version, and system uptime."""
    return _er605.get_router_info() if _er605 else _NO_CONFIG


@mcp.tool()
def get_connected_clients() -> dict:
    """Get all devices on the Deco mesh: hostname, IP, MAC, which node, band."""
    return _deco.get_connected_clients() if _deco else _NO_CONFIG


@mcp.tool()
def get_mesh_health() -> dict:
    """Get Deco node status: online/offline, wired vs wireless backhaul, signal strength."""
    return _deco.get_mesh_health() if _deco else _NO_CONFIG


@mcp.tool()
def get_pihole_stats() -> dict:
    """Get Pi-hole query stats: total queries, blocked count, block percentage, enabled state."""
    return _pihole.get_pihole_stats() if _pihole else _NO_CONFIG


@mcp.tool()
def test_dns_resolution(hostname: str, dns_server: str = None) -> dict:
    """Resolve a hostname and report which DNS server answered and the resolved IPs.
    Optionally specify dns_server (e.g. '8.8.8.8') to bypass Pi-hole."""
    return _test_dns_resolution(hostname, dns_server)


@mcp.tool()
def ping_host(host: str, count: int = 4) -> dict:
    """Ping a host and return latency and packet loss. Works for LAN and internet hosts."""
    return _ping_host(host, count)


@mcp.tool()
def traceroute_host(host: str) -> dict:
    """Traceroute to a host showing each hop and its latency."""
    return _traceroute_host(host)


@mcp.tool()
def run_speedtest() -> dict:
    """Run an internet speed test and return download Mbps, upload Mbps, and ping."""
    return _run_speedtest()


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Run all tests**

```bash
pytest -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/server.py tests/test_server.py
git commit -m "feat: register all 9 diagnostic tools with MCP server"
```

---

## Task 9: Claude Code Registration and Smoke Test

**Files:**
- Create: `.claude/mcp_settings.json`

- [ ] **Step 1: Create `config.json` from example**

```bash
cp config.example.json config.json
```

Open `config.json` and fill in your actual values:
- `er605.host` — router IP (check your Nokia modem's DHCP leases, typically `192.168.0.1`)
- `er605.password` — the admin password you set on the ER605 web UI
- `deco.host` — primary Deco IP (same subnet, typically `192.168.68.1` if Deco is in router mode, or the IP it was assigned if in AP mode)
- `pihole.host` — Pi-hole's IP address
- `pihole.api_token` — found in Pi-hole admin UI at Settings → API / Web interface → Show API token

- [ ] **Step 2: Create `.claude/mcp_settings.json`**

```json
{
  "mcpServers": {
    "network-assistant": {
      "command": "python",
      "args": ["src/server.py"],
      "cwd": "/Users/taylorgay/Documents/Claude/Projects/NetworkAssistant"
    }
  }
}
```

- [ ] **Step 3: Restart Claude Code**

Close and reopen Claude Code in this project directory. The MCP server starts automatically.

- [ ] **Step 4: Smoke test — diagnostics (no credentials needed)**

Ask Claude: *"Ping 8.8.8.8 four times and tell me the average latency."*

Expected: Claude calls `ping_host` and reports latency. If this fails, check `python src/server.py` runs without import errors.

- [ ] **Step 5: Smoke test — Pi-hole**

Ask Claude: *"Are there any Pi-hole stats available?"*

Expected: Claude calls `get_pihole_stats` and returns query counts. If it reports `config.json not found`, verify the file exists and is valid JSON.

- [ ] **Step 6: Smoke test — Deco**

Ask Claude: *"What devices are connected to my network right now?"*

Expected: Claude calls `get_connected_clients` and lists devices. If Deco auth fails, the error message will indicate whether it's a credential or connectivity issue.

- [ ] **Step 7: Smoke test — ER605**

Ask Claude: *"Is my fiber connection up or am I on 5G failover?"*

Expected: Claude calls `get_wan_status`. If the API response format doesn't match (firmware variance), Claude will report the raw response — use that to identify the correct field names and update `er605.py`.

- [ ] **Step 8: Commit**

```bash
git add .claude/mcp_settings.json
git commit -m "chore: register MCP server with Claude Code"
```

---

## Known Limitations (Phase 1)

- **ER605 API format:** Reverse-engineered from community sources. Exact endpoint parameters may vary by firmware version. If `get_wan_status` or `get_router_info` return `error_code != 0`, inspect the `raw` field and cross-reference against browser dev tools traffic captured from your router's web UI.
- **Deco auth:** If the RSA key exchange fails (some older firmware uses a simpler auth), the client falls back to plain MD5 password. If both fail, compare against the HA `tplink_deco` integration for your specific Deco firmware version.
- **Pi-hole v6:** This implementation targets the v5 API (`/admin/api.php`). If you've upgraded Pi-hole to v6, the base URL changes to `/api/` — update `_base` in `PiholeClient` accordingly.
- **Phase 2 (config changes):** Not in scope for this plan. Covered in a separate spec/plan after Phase 1 is validated against real hardware.
