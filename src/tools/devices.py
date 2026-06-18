import json
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mac_vendor_lookup import MacLookup

from src.tools.deco import DecoClient
from src.tools.pihole import PiholeClient

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
