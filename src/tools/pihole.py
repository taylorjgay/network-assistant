import httpx

_BLOCKED_STATUSES = {1, 4, 5, 6, 10, 12, 13, 14, 15}


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
            queries = data.get("queries", {})
            gravity = data.get("gravity", {})
            return {
                "success": True,
                "queries_today": queries.get("total", 0),
                "blocked_today": queries.get("blocked", 0),
                "block_pct": round(float(queries.get("percent_blocked", 0.0)), 1),
                "domains_blocked": gravity.get("domains_being_blocked", 0),
                "enabled": blocking_resp.json().get("blocking") == "enabled",
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
