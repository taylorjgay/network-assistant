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
            if data.get("FTLnotrunning") is True:
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
        except httpx.ConnectError as e:
            return {"success": False, "error": str(e),
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
