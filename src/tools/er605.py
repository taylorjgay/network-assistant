import json
import httpx


_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}


def _rsa_encrypt(plaintext: str, modulus_hex: str) -> str:
    """RSA with ER605 'nopadding': right-pad plaintext to key size with zeros, then textbook RSA."""
    n = int(modulus_hex, 16)
    key_size = (n.bit_length() + 7) // 8
    encoded = plaintext.encode("utf-8")
    padded = encoded + b"\x00" * (key_size - len(encoded))
    m = int.from_bytes(padded, "big")
    return format(pow(m, 65537, n), "0256x")


class ER605Client:
    def __init__(self, host: str, username: str, password: str):
        self.host = host
        self.username = username
        self.password = password
        self._base = f"https://{host}"
        self._login_url = f"{self._base}/cgi-bin/luci/;stok=/login?form=login"

    def _headers(self) -> dict:
        return {
            **_HEADERS,
            "Origin": self._base,
            "Referer": f"{self._base}/webpages/login.html",
        }

    def _post_form(self, client: httpx.Client, url: str, payload: dict) -> dict:
        resp = client.post(url, data={"data": json.dumps(payload)}, headers=self._headers())
        return resp.json()

    def _get_uptime(self, client: httpx.Client, step1_result: dict) -> str:
        """Get uptime for password encryption from locale endpoint (operation=read format)."""
        uptime = step1_result.get("uptime")
        if uptime is not None:
            return str(uptime)
        try:
            resp = client.post(
                f"{self._base}/cgi-bin/luci/;stok=/locale?form=lang",
                data={"operation": "read"},
                headers=self._headers(),
            )
            uptime = resp.json().get("result", {}).get("uptime")
            if uptime is not None:
                return str(uptime)
        except Exception:
            pass
        return "0"

    def _login(self, client: httpx.Client) -> tuple[str | None, str]:
        """Return (stok, error_detail). stok is None on failure."""
        resp1 = self._post_form(client, self._login_url, {"method": "get"})
        if resp1.get("error_code") != "0":
            return None, f"pre-login key exchange failed: error_code={resp1.get('error_code')}"

        result = resp1.get("result", {})
        modulus_hex = result["password"][0]

        uptime = self._get_uptime(client, result)
        plaintext = f"{self.password}_{uptime}"
        encrypted = _rsa_encrypt(plaintext, modulus_hex)

        resp2 = self._post_form(client, self._login_url, {
            "method": "login",
            "params": {"username": self.username, "password": encrypted},
        })
        if resp2.get("error_code") != "0":
            code = resp2.get("error_code")
            detail = f"login rejected: error_code={code}"
            if code == "700":
                detail += " (wrong password or uptime mismatch)"
            return None, detail

        stok = resp2.get("result", {}).get("stok")
        return stok, ""

    def _api(self, client: httpx.Client, stok: str, resource: str, form: str) -> dict:
        url = f"{self._base}/cgi-bin/luci/;stok={stok}/admin/{resource}?form={form}"
        return self._post_form(client, url, {"method": "get"})

    def _api_set(self, client: httpx.Client, stok: str, resource: str, form: str, params: dict) -> dict:
        url = f"{self._base}/cgi-bin/luci/;stok={stok}/admin/{resource}?form={form}"
        return self._post_form(client, url, {"method": "set", "params": params})

    def _api_add(self, client: httpx.Client, stok: str, resource: str, form: str, params: dict) -> dict:
        url = f"{self._base}/cgi-bin/luci/;stok={stok}/admin/{resource}?form={form}"
        return self._post_form(client, url, {"method": "add", "params": params})

    def _api_del(self, client: httpx.Client, stok: str, resource: str, form: str, params: dict) -> dict:
        url = f"{self._base}/cgi-bin/luci/;stok={stok}/admin/{resource}?form={form}"
        return self._post_form(client, url, {"method": "del", "params": params})

    def get_wan_policy(self) -> dict:
        url = self._base
        try:
            with httpx.Client(verify=False, timeout=10) as client:
                stok, err = self._login(client)
                if stok is None:
                    return {
                        "success": False,
                        "error": f"ER605 authentication failed: {err}",
                        "suggestion": "Check er605.username and er605.password in config.json",
                        "attempted": url,
                    }
                data = self._api(client, stok, "network", "wan_load_balance")

            if data.get("error_code") != "0":
                return {
                    "success": False,
                    "error": f"ER605 WAN policy endpoint error {data.get('error_code')}",
                    "suggestion": "This endpoint may not be accessible on standalone ER605 firmware 2.x. Try the Web UI instead.",
                    "attempted": url,
                    "raw": data,
                }

            result = data.get("result", {})
            return {
                "success": True,
                "mode": result.get("mode"),
                "primary_wan": result.get("primary_wan"),
                "health_check": result.get("health_check", {}),
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def set_wan_priority(self, primary_wan: str, dry_run: bool = False) -> dict:
        url = self._base
        if primary_wan not in ("WAN1", "WAN2", "auto"):
            return {
                "success": False,
                "error": f"Invalid primary_wan '{primary_wan}'",
                "suggestion": "Use 'WAN1', 'WAN2', or 'auto' (restore automatic failover)",
                "attempted": url,
            }
        params = {"primary_wan": primary_wan}
        try:
            with httpx.Client(verify=False, timeout=10) as client:
                stok, err = self._login(client)
                if stok is None:
                    return {
                        "success": False,
                        "error": f"ER605 authentication failed: {err}",
                        "suggestion": "Check er605.username and er605.password in config.json",
                        "attempted": url,
                    }
                if dry_run:
                    return {
                        "success": True,
                        "dry_run": True,
                        "would_send": {
                            "resource": "network",
                            "form": "wan_load_balance",
                            "method": "set",
                            "params": params,
                        },
                    }
                data = self._api_set(client, stok, "network", "wan_load_balance", params)

            if data.get("error_code") != "0":
                return {
                    "success": False,
                    "error": f"ER605 set WAN priority error {data.get('error_code')}",
                    "suggestion": "This endpoint may not be accessible on standalone ER605 firmware 2.x. Try the Web UI instead.",
                    "attempted": url,
                    "raw": data,
                }

            return {"success": True, "primary_wan": primary_wan}
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def get_port_forwards(self) -> dict:
        url = self._base
        try:
            with httpx.Client(verify=False, timeout=10) as client:
                stok, err = self._login(client)
                if stok is None:
                    return {
                        "success": False,
                        "error": f"ER605 authentication failed: {err}",
                        "suggestion": "Check er605.username and er605.password in config.json",
                        "attempted": url,
                    }
                data = self._api(client, stok, "nat", "virtual_server")

            if data.get("error_code") != "0":
                return {
                    "success": False,
                    "error": f"ER605 port forward endpoint error {data.get('error_code')}",
                    "suggestion": "This endpoint may not be accessible on standalone ER605 firmware 2.x. Try the Web UI instead.",
                    "attempted": url,
                    "raw": data,
                }

            rules = data.get("result", {}).get("virtual_server", [])
            return {
                "success": True,
                "rules": [
                    {
                        "id": r.get("index") or r.get("id"),
                        "name": r.get("name"),
                        "external_port": r.get("external_port"),
                        "internal_ip": r.get("internal_ip"),
                        "internal_port": r.get("internal_port"),
                        "protocol": r.get("protocol"),
                        "enabled": r.get("enable") or r.get("enabled"),
                    }
                    for r in rules
                ],
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def add_port_forward(
        self,
        name: str,
        external_port: int,
        internal_ip: str,
        internal_port: int,
        protocol: str = "tcp",
        dry_run: bool = False,
    ) -> dict:
        url = self._base
        if protocol not in ("tcp", "udp", "both"):
            return {
                "success": False,
                "error": f"Invalid protocol '{protocol}'",
                "suggestion": "Use 'tcp', 'udp', or 'both'",
                "attempted": url,
            }
        params = {
            "name": name,
            "external_port": external_port,
            "internal_ip": internal_ip,
            "internal_port": internal_port,
            "protocol": protocol,
        }
        try:
            with httpx.Client(verify=False, timeout=10) as client:
                stok, err = self._login(client)
                if stok is None:
                    return {
                        "success": False,
                        "error": f"ER605 authentication failed: {err}",
                        "suggestion": "Check er605.username and er605.password in config.json",
                        "attempted": url,
                    }
                if dry_run:
                    return {
                        "success": True,
                        "dry_run": True,
                        "would_send": {
                            "resource": "nat",
                            "form": "virtual_server",
                            "method": "add",
                            "params": params,
                        },
                    }
                data = self._api_add(client, stok, "nat", "virtual_server", params)

            if data.get("error_code") != "0":
                return {
                    "success": False,
                    "error": f"ER605 add port forward error {data.get('error_code')}",
                    "suggestion": "This endpoint may not be accessible on standalone ER605 firmware 2.x. Try the Web UI instead.",
                    "attempted": url,
                    "raw": data,
                }

            return {"success": True, "rule": data.get("result", {})}
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def remove_port_forward(self, rule_id: str, dry_run: bool = False) -> dict:
        url = self._base
        params = {"index": rule_id}
        try:
            with httpx.Client(verify=False, timeout=10) as client:
                stok, err = self._login(client)
                if stok is None:
                    return {
                        "success": False,
                        "error": f"ER605 authentication failed: {err}",
                        "suggestion": "Check er605.username and er605.password in config.json",
                        "attempted": url,
                    }
                if dry_run:
                    return {
                        "success": True,
                        "dry_run": True,
                        "would_send": {
                            "resource": "nat",
                            "form": "virtual_server",
                            "method": "del",
                            "params": params,
                        },
                    }
                data = self._api_del(client, stok, "nat", "virtual_server", params)

            if data.get("error_code") != "0":
                return {
                    "success": False,
                    "error": f"ER605 remove port forward error {data.get('error_code')}",
                    "suggestion": "This endpoint may not be accessible on standalone ER605 firmware 2.x. Try the Web UI instead.",
                    "attempted": url,
                    "raw": data,
                }

            return {"success": True, "removed_id": rule_id}
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def get_firewall_rules(self) -> dict:
        url = self._base
        try:
            with httpx.Client(verify=False, timeout=10) as client:
                stok, err = self._login(client)
                if stok is None:
                    return {
                        "success": False,
                        "error": f"ER605 authentication failed: {err}",
                        "suggestion": "Check er605.username and er605.password in config.json",
                        "attempted": url,
                    }
                data = self._api(client, stok, "firewall", "acl_ip")

            if data.get("error_code") != "0":
                return {
                    "success": False,
                    "error": f"ER605 firewall endpoint error {data.get('error_code')}",
                    "suggestion": "This endpoint may not be accessible on standalone ER605 firmware 2.x. Try the Web UI instead.",
                    "attempted": url,
                    "raw": data,
                }

            rules = data.get("result", {}).get("acl_ip", [])
            return {
                "success": True,
                "rules": [
                    {
                        "id": r.get("index") or r.get("id"),
                        "name": r.get("name"),
                        "src_ip": r.get("src_ip", ""),
                        "dst_ip": r.get("dst_ip", ""),
                        "action": r.get("action"),
                        "protocol": r.get("protocol"),
                        "enabled": r.get("enable") or r.get("enabled"),
                    }
                    for r in rules
                ],
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def add_firewall_rule(
        self,
        name: str,
        src_ip: str = "",
        dst_ip: str = "",
        action: str = "deny",
        protocol: str = "all",
        dry_run: bool = False,
    ) -> dict:
        url = self._base
        if action not in ("deny", "allow"):
            return {
                "success": False,
                "error": f"Invalid action '{action}'",
                "suggestion": "Use 'deny' or 'allow'",
                "attempted": url,
            }
        if protocol not in ("tcp", "udp", "icmp", "all"):
            return {
                "success": False,
                "error": f"Invalid protocol '{protocol}'",
                "suggestion": "Use 'tcp', 'udp', 'icmp', or 'all'",
                "attempted": url,
            }
        params = {
            "name": name,
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "action": action,
            "protocol": protocol,
        }
        try:
            with httpx.Client(verify=False, timeout=10) as client:
                stok, err = self._login(client)
                if stok is None:
                    return {
                        "success": False,
                        "error": f"ER605 authentication failed: {err}",
                        "suggestion": "Check er605.username and er605.password in config.json",
                        "attempted": url,
                    }
                if dry_run:
                    return {
                        "success": True,
                        "dry_run": True,
                        "would_send": {
                            "resource": "firewall",
                            "form": "acl_ip",
                            "method": "add",
                            "params": params,
                        },
                    }
                data = self._api_add(client, stok, "firewall", "acl_ip", params)

            if data.get("error_code") != "0":
                return {
                    "success": False,
                    "error": f"ER605 add firewall rule error {data.get('error_code')}",
                    "suggestion": "This endpoint may not be accessible on standalone ER605 firmware 2.x. Try the Web UI instead.",
                    "attempted": url,
                    "raw": data,
                }

            return {"success": True, "rule": data.get("result", {})}
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def remove_firewall_rule(self, rule_id: str, dry_run: bool = False) -> dict:
        url = self._base
        params = {"index": rule_id}
        try:
            with httpx.Client(verify=False, timeout=10) as client:
                stok, err = self._login(client)
                if stok is None:
                    return {
                        "success": False,
                        "error": f"ER605 authentication failed: {err}",
                        "suggestion": "Check er605.username and er605.password in config.json",
                        "attempted": url,
                    }
                if dry_run:
                    return {
                        "success": True,
                        "dry_run": True,
                        "would_send": {
                            "resource": "firewall",
                            "form": "acl_ip",
                            "method": "del",
                            "params": params,
                        },
                    }
                data = self._api_del(client, stok, "firewall", "acl_ip", params)

            if data.get("error_code") != "0":
                return {
                    "success": False,
                    "error": f"ER605 remove firewall rule error {data.get('error_code')}",
                    "suggestion": "This endpoint may not be accessible on standalone ER605 firmware 2.x. Try the Web UI instead.",
                    "attempted": url,
                    "raw": data,
                }

            return {"success": True, "removed_id": rule_id}
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def get_wan_status(self) -> dict:
        url = self._base
        try:
            with httpx.Client(verify=False, timeout=10) as client:
                stok, err = self._login(client)
                if stok is None:
                    return {
                        "success": False,
                        "error": f"ER605 authentication failed: {err}",
                        "suggestion": "Check er605.username and er605.password in config.json",
                        "attempted": url,
                    }
                data = self._api(client, stok, "interface", "status2")

            if data.get("error_code") != "0":
                return {
                    "success": False,
                    "error": f"ER605 interface endpoint error {data.get('error_code')}",
                    "suggestion": "WAN status endpoint may differ on this firmware version",
                    "attempted": url,
                    "raw": data,
                }

            interfaces = data.get("result", {}).get("normal", [])
            wan_ports = [i for i in interfaces if i.get("t_name", "").startswith("WAN")]
            return {
                "success": True,
                "interfaces": [
                    {
                        "name": i.get("t_name"),
                        "up": i.get("t_isup"),
                        "ip": i.get("ipaddr"),
                        "proto": i.get("t_proto"),
                        "gateway": i.get("gateway"),
                        "dns1": i.get("dns1"),
                    }
                    for i in wan_ports
                ],
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def get_router_info(self) -> dict:
        url = self._base
        try:
            with httpx.Client(verify=False, timeout=10) as client:
                stok, err = self._login(client)
                if stok is None:
                    return {
                        "success": False,
                        "error": f"ER605 authentication failed: {err}",
                        "suggestion": "Check er605.username and er605.password in config.json",
                        "attempted": url,
                    }
                fw_data = self._api(client, stok, "firmware", "upgrade")
                sys_data = self._api(client, stok, "sys_status", "all_usage")
                locale_resp = client.post(
                    f"{self._base}/cgi-bin/luci/;stok=/locale?form=lang",
                    data={"operation": "read"},
                    headers=self._headers(),
                )
                locale_result = locale_resp.json().get("result", {})

            if fw_data.get("error_code") != "0":
                return {
                    "success": False,
                    "error": f"ER605 firmware endpoint error {fw_data.get('error_code')}",
                    "suggestion": "Firmware info endpoint may differ on this firmware version",
                    "attempted": url,
                    "raw": fw_data,
                }

            fw = fw_data.get("result", {})
            sys = sys_data.get("result", {}) if sys_data.get("error_code") == "0" else {}
            cpu = sys.get("cpu_usage", {})
            mem = sys.get("mem_usage", {}).get("mem")
            return {
                "success": True,
                "model": fw.get("hardware_version") or fw.get("model"),
                "firmware": fw.get("firmware_version"),
                "uptime_seconds": locale_result.get("uptime"),
                "cpu_percent": round(sum(cpu.values()) / len(cpu)) if cpu else None,
                "mem_percent": mem,
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}
