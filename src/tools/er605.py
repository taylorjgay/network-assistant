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
        resp = client.post(f"{self._base}/", json={
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
