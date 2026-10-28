import json
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mac_vendor_lookup import MacLookup

from src.tools.deco import DecoClient, cached_result as deco_cached_result
from src.tools.pihole import PiholeClient

# Deco client placement older than this is not shown (the dashboard refreshes it every ~5 min).
_DECO_CLIENTS_MAX_AGE = 15 * 60.0

# Devices that report no name get one made up by the Deco from their type and the last MAC
# digits ("tablet_72F0" for c4:95:00:b9:72:f0, an Echo Dot). Not worth showing as a hostname.
_GENERATED_DECO_NAME = re.compile(r"^[a-z]+_[0-9A-F]{4}$")

_mac_lookup = MacLookup()
_labels_lock = threading.Lock()


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

    def get_network_devices(self, deep_scan: bool = False) -> dict:
        try:
            if deep_scan:
                self._ping_sweep()

            raw_devices = self._parse_arp_cache()
            labels = self._load_labels()

            devices: dict = {}
            for d in raw_devices:
                mac = _normalize_mac(d["mac"]) or d["mac"]
                devices[d["ip"]] = {
                    "ip": d["ip"],
                    "mac": mac,
                    "label": labels.get(mac),
                    "hostname": None,
                    "vendor": self._lookup_vendor(mac),
                    "online": True,
                    "pihole_queries_total": None,
                    "pihole_last_seen": None,
                    "deco_node": None,
                    "deco_signal_dbm": None,
                    "connection_type": None,
                    "access_point": None,
                    "wifi_band": None,
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

    def label_device(self, mac: str, label: str) -> dict:
        normalized = _normalize_mac(mac)
        if normalized is None:
            return {
                "success": False,
                "error": f"Invalid MAC address format '{mac}'",
                "suggestion": "Use format AA:BB:CC:DD:EE:FF",
            }
        with _labels_lock:
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
        with _labels_lock:
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

    def _parse_arp_cache(self) -> list[dict]:
        try:
            result = subprocess.run(['arp', '-an'], capture_output=True, text=True, timeout=5)
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

    def _lookup_vendor(self, mac: str) -> Optional[str]:
        try:
            return _mac_lookup.lookup(mac)
        except Exception:
            return None

    def _enrich_pihole(self, devices: dict) -> None:
        if self._cfg is None:
            return
        try:
            result = PiholeClient(**vars(self._cfg.pihole)).get_clients()
            if not result.get("success"):
                return
            # Match by MAC, never by IP, and take no hostnames from Pi-hole. Its network table
            # keeps old addresses per device and attaches stale names to them: on 2026-10-28 it
            # named 57 addresses "homeserver.lan", which then landed on whichever device held
            # each address.
            by_mac = {d["mac"]: d for d in devices.values() if d.get("mac")}
            for client in result.get("clients", []):
                device = by_mac.get(client.get("mac"))
                if device is None:
                    continue
                device["pihole_queries_total"] = client.get("query_count")
                last_query = client.get("last_query")
                if last_query:
                    device["pihole_last_seen"] = datetime.fromtimestamp(
                        last_query, tz=timezone.utc
                    ).isoformat()
        except Exception:
            pass

    def _enrich_deco(self, devices: dict) -> None:
        if self._cfg is None:
            return
        try:
            result = DecoClient(**vars(self._cfg.deco)).get_mesh_health()
            if result.get("success"):
                for node in result.get("nodes", []):
                    ip = node.get("ip")
                    if ip and ip in devices:
                        devices[ip]["deco_node"] = node.get("nickname")
                        devices[ip]["deco_signal_dbm"] = node.get("signal_level_dbm")
                        devices[ip]["connection_type"] = "deco_node"
        except Exception:
            pass
        self._enrich_deco_clients(devices)

    def _enrich_deco_clients(self, devices: dict) -> None:
        """Which Deco each device is on, and how. Read-only: the client list costs ~25s of
        Deco time, so the dashboard refreshes it in the background (api._refresh_deco_clients)
        and this uses whatever is cached."""
        clients = deco_cached_result("clients", _DECO_CLIENTS_MAX_AGE)
        if not clients:
            return
        by_mac = {c["mac"]: c for c in clients.get("clients", []) if c.get("mac")}
        for device in devices.values():
            c = by_mac.get(device["mac"])
            if c is None or device["connection_type"] == "deco_node":
                continue
            device["access_point"] = c.get("deco_node")
            device["wifi_band"] = c.get("band")
            device["connection_type"] = c.get("connection")
            name = c.get("hostname")
            if not device["hostname"] and name and not _GENERATED_DECO_NAME.match(name):
                device["hostname"] = name

    def _ping_sweep(self) -> None:
        """Ping all hosts in 192.168.0.1-254 in parallel to populate the ARP cache."""
        def ping_one(ip: str) -> None:
            try:
                subprocess.run(
                    ['ping', '-c', '1', '-W', '1', ip],
                    capture_output=True, timeout=3
                )
            except Exception:
                pass

        ips = [f'192.168.0.{i}' for i in range(1, 255)]
        with ThreadPoolExecutor(max_workers=50) as executor:
            list(executor.map(ping_one, ips))
