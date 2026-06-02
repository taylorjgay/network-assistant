import httpx

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
        resp = client.post(f"{self._base}/auth", json={"password": self.api_token})
        resp.raise_for_status()
        session = resp.json().get("session", {})
        return session.get("sid") if session.get("valid") else None

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
