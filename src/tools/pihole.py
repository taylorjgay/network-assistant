from collections import defaultdict
from datetime import datetime, timezone
import threading
import time
import httpx

# Reuse Pi-hole sessions to avoid hammering /api/auth (Pi-hole v6 rate-limits it).
# TTL is 4 min; Pi-hole v6 default session lifetime is 5 min.
_sid_cache: dict[str, tuple[str, float]] = {}
_sid_lock = threading.Lock()
_auth_locks: dict[str, threading.Lock] = {}
_auth_locks_meta = threading.Lock()
_SID_TTL = 240


def _get_auth_lock(host: str) -> threading.Lock:
    with _auth_locks_meta:
        if host not in _auth_locks:
            _auth_locks[host] = threading.Lock()
        return _auth_locks[host]

_BLOCKED_STATUSES = {1, 4, 5, 6, 10, 12, 13, 14, 15}

_STATUS_NAMES = {
    1: "blocked", 2: "forwarded", 3: "cached", 4: "blocked",
    5: "blocked", 6: "blocked", 7: "forwarded", 8: "forwarded",
    9: "forwarded", 10: "blocked", 11: "forwarded", 12: "blocked",
    13: "blocked", 14: "blocked", 15: "blocked",
}


class PiholeClient:
    def __init__(self, host: str, api_token: str):
        self.host = host
        self.api_token = api_token
        self._base = f"http://{host}/api"

    def _get_sid(self, client: httpx.Client) -> str | None:
        with _sid_lock:
            cached = _sid_cache.get(self.host)
            if cached and time.monotonic() < cached[1]:
                return cached[0]
        # Serialize auth per host so simultaneous calls share one session.
        with _get_auth_lock(self.host):
            with _sid_lock:
                cached = _sid_cache.get(self.host)
                if cached and time.monotonic() < cached[1]:
                    return cached[0]
            resp = client.post(f"{self._base}/auth", json={"password": self.api_token})
            resp.raise_for_status()
            session = resp.json().get("session", {})
            sid = session.get("sid") if session.get("valid") else None
            if sid:
                with _sid_lock:
                    _sid_cache[self.host] = (sid, time.monotonic() + _SID_TTL)
            return sid

    def get_pihole_stats(self) -> dict:
        """Get Pi-hole summary statistics."""
        url = f"{self._base}/stats/summary"
        try:
            with httpx.Client(timeout=10) as client:
                sid = self._get_sid(client)
                if sid is None:
                    return {"success": False, "error": "Authentication failed",
                            "suggestion": "Check api_token in config.json", "attempted": url}
                resp = client.get(url, headers={"X-FTL-SID": sid})
                resp.raise_for_status()
                blocking_resp = client.get(
                    f"{self._base}/dns/blocking", headers={"X-FTL-SID": sid}
                )
                blocking_resp.raise_for_status()
                data = resp.json()
                blocking_data = blocking_resp.json()
            queries = data.get("queries", {})
            gravity = data.get("gravity", {})
            return {
                "success": True,
                "queries_today": queries.get("total", 0),
                "blocked_today": queries.get("blocked", 0),
                "block_pct": round(float(queries.get("percent_blocked", 0.0)), 1),
                "domains_blocked": gravity.get("domains_being_blocked", 0),
                "enabled": blocking_data.get("blocking") == "enabled",
            }
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"HTTP {e.response.status_code}",
                    "suggestion": "Check Pi-hole host in config.json and that the admin interface is reachable",
                    "attempted": url}
        except httpx.ConnectError as e:
            return {"success": False, "error": str(e),
                    "suggestion": f"Cannot reach Pi-hole at {self.host} — verify IP in config.json",
                    "attempted": url}
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def test_dns_resolution(self, hostname: str) -> dict:
        """Check if Pi-hole has recently blocked a hostname."""
        url = f"{self._base}/queries"
        try:
            with httpx.Client(timeout=10) as client:
                sid = self._get_sid(client)
                if sid is None:
                    return {"success": False, "hostname": hostname,
                            "error": "Authentication failed",
                            "suggestion": "Check api_token in config.json", "attempted": url}
                resp = client.get(url, headers={"X-FTL-SID": sid},
                                  params={"domain": hostname, "limit": 10})
                resp.raise_for_status()
            queries = resp.json().get("queries", [])
            blocked = [q for q in queries if q.get("status") in _BLOCKED_STATUSES]
            return {
                "success": True,
                "hostname": hostname,
                "recent_queries": len(queries),
                "recent_blocked": len(blocked),
                "is_recently_blocked": len(blocked) > 0,
            }
        except Exception as e:
            return {"success": False, "hostname": hostname, "error": str(e),
                    "suggestion": "Check Pi-hole connectivity", "attempted": url}

    def get_query_log(
        self,
        blocked: bool | None = None,
        domain: str | None = None,
        client: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Get recent DNS query log from Pi-hole."""
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
                raw_queries = resp.json().get("queries", [])
            queries = []
            for q in raw_queries:
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
                raw = resp.json().get("domains", [])
            if isinstance(raw, dict):
                domains = [{"domain": k, "count": v} for k, v in sorted(raw.items(), key=lambda x: -x[1])]
            else:
                domains = sorted(raw, key=lambda x: -x.get("count", 0))
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
                entries = resp.json().get("domains", [])
            allow, block = [], []
            for entry in entries:
                item = {
                    "domain": entry.get("domain", ""),
                    "kind": "regex" if entry.get("kind") in (1, "regex") else "exact",
                    "enabled": entry.get("enabled", True),
                    "comment": entry.get("comment") or "",
                }
                if entry.get("type") in ("allow", 0):
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

    def get_pihole_system(self) -> dict:
        """Get Pi-hole system info: CPU load, RAM usage, uptime, hostname."""
        url = f"{self._base}/info/system"
        try:
            with httpx.Client(timeout=10) as c:
                sid = self._get_sid(c)
                if sid is None:
                    return {"success": False, "error": "Authentication failed",
                            "suggestion": "Check api_token in config.json", "attempted": url}
                resp = c.get(url, headers={"X-FTL-SID": sid})
                resp.raise_for_status()
                sys_data = resp.json().get("system", {})
            cpu = sys_data.get("cpu", {})
            mem = sys_data.get("memory", {}).get("ram", {})
            load_raw = cpu.get("load", {}).get("raw", [0, 0, 0])
            return {
                "success": True,
                "hostname": sys_data.get("hostname", ""),
                "uptime_seconds": sys_data.get("uptime", 0),
                "cpu_percent": round(cpu.get("%cpu", 0)),
                "mem_percent": round(mem.get("%used", 0)),
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
                entries = resp.json().get("clients", [])
            clients = []
            for entry in entries:
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
