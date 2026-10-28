import json
import time
import httpx


# Monotonic time of this process's most recent successful ER605 login. ER605Session
# uses it to tell its own tool calls apart from someone opening the web UI.
_last_login_at = 0.0

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


def _normalize_mac(mac: str | None) -> str | None:
    """ER605 sends `34-9F-7B-2D-D8-A8`; devices.json and the rest of the app use `34:9f:7b:2d:d8:a8`."""
    return mac.replace("-", ":").lower() if mac else None


def _hms_to_seconds(value: str | None) -> int | None:
    """Lease time remaining as `H:MM:SS` (hours may exceed 24); None for anything else."""
    try:
        h, m, s = (int(p) for p in (value or "").split(":"))
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


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
        try:
            return resp.json()
        except ValueError:
            # Not JSON. Keep the 1014 code callers expect, but carry what the router actually
            # said: a wrong endpoint name answers 404 or 500 with plain text, not a firmware error.
            return {"error_code": "1014", "_empty_body": True,
                    "http_status": resp.status_code, "body": resp.text[:200]}

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
        if stok:
            global _last_login_at
            _last_login_at = time.monotonic()
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

    def _read(self, what: str, *endpoints: tuple[str, str]) -> dict:
        """Log in once and read admin endpoints in order.

        Returns {"success": True, "results": [result, ...]} or a structured error. Endpoint
        names come from the router's own web UI JS (/webpages/js/chunk-common.*.js); guessed
        names fail with 1014, HTTP 404 or HTTP 500 depending on how wrong they are.
        """
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
                results = []
                for resource, form in endpoints:
                    data = self._api(client, stok, resource, form)
                    if data.get("error_code") != "0":
                        return {
                            "success": False,
                            "error": f"ER605 {what} endpoint {resource}?form={form} error {data.get('error_code')}",
                            "suggestion": "Check the endpoint name against the router web UI JS",
                            "attempted": f"{url}/cgi-bin/luci/;stok=.../admin/{resource}?form={form}",
                            "raw": data,
                        }
                    results.append(data.get("result"))
            return {"success": True, "results": results}
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}

    def get_wan_policy(self) -> dict:
        read = self._read("WAN policy", ("balance", "line_backup"), ("balance", "balance_basic"))
        if not read["success"]:
            return read
        backups, basic = read["results"]
        backup = (backups or [{}])[0]
        failover_on = backup.get("state") == "on"
        balance_on = (basic or {}).get("balance_state") == "on"
        masters = backup.get("master_iface") or []
        return {
            "success": True,
            "mode": "load_balance" if balance_on else "failover" if failover_on else "single",
            "primary_wan": masters[0] if masters else None,
            "backup_wan": backup.get("slave_iface"),
            "failover_enabled": failover_on,
            "failover_mode": backup.get("mode"),
            "load_balance_enabled": balance_on,
        }

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
        read = self._read("port forward", ("nat", "vs"))
        if not read["success"]:
            return read
        rules = read["results"][0] or []
        return {
            "success": True,
            "rules": [
                {
                    # No id until removal is wired to the real endpoint; the dashboard
                    # disables Remove for rules without one.
                    "id": None,
                    "name": r.get("name"),
                    "external_port": r.get("external_port"),
                    "internal_ip": r.get("ipaddr"),
                    "internal_port": r.get("internal_port"),
                    "protocol": (r.get("protocol") or "").lower(),
                    "enabled": r.get("enable") == "on",
                    "wan_interfaces": r.get("interface") or [],
                }
                for r in rules
            ],
            "count": len(rules),
        }

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
        read = self._read("firewall ACL", ("access_ctl", "acl_inner"))
        if not read["success"]:
            return read
        rules = read["results"][0] or []
        # No "enabled" field: the router sends `flag` and `user` ("1"), and which one is
        # the on/off switch is not confirmed.
        return {
            "success": True,
            "rules": [
                {
                    "name": r.get("name"),
                    "action": r.get("policy"),
                    "source": r.get("src"),
                    "source_type": r.get("is_src"),
                    "destination": r.get("dest"),
                    "destination_type": r.get("is_dst"),
                    "service": r.get("service"),
                    "zones": r.get("zone") or [],
                    "schedule": r.get("time"),
                    "ip_version": r.get("iptype"),
                }
                for r in rules
            ],
            "count": len(rules),
        }

    def get_dhcp_leases(self) -> dict:
        read = self._read("DHCP", ("dhcps", "client"), ("dhcps", "reservation"))
        if not read["success"]:
            return read
        clients, reservations = (r or [] for r in read["results"])
        return {
            "success": True,
            "leases": [
                {
                    "ip": c.get("ipaddr"),
                    "mac": _normalize_mac(c.get("macaddr")),
                    "hostname": None if c.get("name") in (None, "", "--") else c.get("name"),
                    "lease_remaining": c.get("leasetime"),
                    "lease_remaining_seconds": _hms_to_seconds(c.get("leasetime")),
                }
                for c in clients
            ],
            "reservations": [
                {
                    "ip": r.get("ip"),
                    "mac": _normalize_mac(r.get("mac")),
                    "note": r.get("note") or None,
                    "enabled": r.get("enable") == "on",
                }
                for r in reservations
            ],
            "lease_count": len(clients),
            "reservation_count": len(reservations),
        }

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
            return parse_wan_status(data, url)
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
            return parse_router_info(fw_data, sys_data, locale_result.get("uptime"), url)
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to ER605",
                "suggestion": f"Verify er605.host in config.json — tried {self.host}",
                "attempted": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "", "attempted": url}


def parse_wan_status(data: dict, url: str) -> dict:
    """Shape an `interface/status2` response into the get_wan_status result."""
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


def parse_router_info(fw_data: dict, sys_data: dict, uptime, url: str) -> dict:
    """Shape `firmware/upgrade` + `sys_status/all_usage` responses into the get_router_info result."""
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
        "uptime_seconds": uptime,
        "cpu_percent": round(sum(cpu.values()) / len(cpu)) if cpu else None,
        "mem_percent": mem,
    }


class ER605Evicted(Exception):
    """A login from outside this process (normally the web UI) replaced our session."""


class ER605Session:
    """One long-lived ER605 login for background polling.

    The ER605 allows a single admin session: every login kicks out the previous one,
    including a person using the web UI. Reusing one session means polling only logs in
    when it must. The stok is bound to the `sysauth` cookie, so the session keeps one
    client for its lifetime (a stok sent from a fresh client gets 704).
    """

    _EXPIRED = "704"  # stok unknown: session timed out or the router rebooted
    _EVICTED = "711"  # stok replaced by a newer login

    def __init__(self, host: str, username: str, password: str):
        self._er = ER605Client(host, username, password)
        self._client: httpx.Client | None = None
        self._stok: str | None = None
        self._logged_in_at = 0.0

    def _open(self) -> None:
        self.close()
        self._client = httpx.Client(verify=False, timeout=10)
        stok, err = self._er._login(self._client)
        if stok is None:
            self.close()
            raise RuntimeError(f"ER605 authentication failed: {err}")
        self._stok = stok
        self._logged_in_at = _last_login_at

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None
        self._stok = None

    def get(self, resource: str, form: str) -> dict:
        """Read an admin endpoint. Raises ER605Evicted if someone else took the session."""
        if self._stok is None:
            self._open()
        data = self._er._api(self._client, self._stok, resource, form)
        code = str(data.get("error_code"))
        if code == self._EVICTED and _last_login_at <= self._logged_in_at:
            self.close()
            raise ER605Evicted()
        if code in (self._EXPIRED, self._EVICTED):
            # Timed out, or replaced by one of this process's own tool calls: log in again.
            self._open()
            data = self._er._api(self._client, self._stok, resource, form)
        return data

    def uptime(self):
        """Router uptime in seconds (unauthenticated locale endpoint)."""
        if self._client is None:
            self._open()
        resp = self._client.post(
            f"{self._er._base}/cgi-bin/luci/;stok=/locale?form=lang",
            data={"operation": "read"},
            headers=self._er._headers(),
        )
        return resp.json().get("result", {}).get("uptime")
