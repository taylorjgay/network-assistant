import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mac_vendor_lookup import MacLookup

from src.tools.deco import DecoClient
from src.tools.pihole import PiholeClient

_mac_lookup = MacLookup()


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
