import json
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import subprocess

from src.tools.devices import DeviceInventory, _normalize_mac


def _cfg():
    return SimpleNamespace(
        pihole=SimpleNamespace(host="192.168.0.200", api_token="test_token"),
        deco=SimpleNamespace(host="192.168.0.100", password="test_pass"),
    )


# --- _normalize_mac ---

def test_normalize_mac_standard():
    assert _normalize_mac("AA:BB:CC:DD:EE:FF") == "aa:bb:cc:dd:ee:ff"


def test_normalize_mac_short_hex():
    # macOS arp -a uses shortened hex like a8:9:2:ab:cd:ef
    assert _normalize_mac("a8:9:2:ab:cd:ef") == "a8:09:02:ab:cd:ef"


def test_normalize_mac_already_normal():
    assert _normalize_mac("aa:bb:cc:dd:ee:ff") == "aa:bb:cc:dd:ee:ff"


def test_normalize_mac_invalid():
    assert _normalize_mac("not-a-mac") is None
    assert _normalize_mac("ZZ:BB:CC:DD:EE:FF") is None


# --- label_device ---

def test_label_device_adds_new(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    result = inv.label_device("AA:BB:CC:DD:EE:FF", "Xbox Series X")

    assert result["success"] is True
    assert result["mac"] == "aa:bb:cc:dd:ee:ff"
    assert result["label"] == "Xbox Series X"
    data = json.loads((tmp_path / "devices.json").read_text())
    assert data["aa:bb:cc:dd:ee:ff"] == "Xbox Series X"


def test_label_device_overwrites_existing(tmp_path):
    labels_file = tmp_path / "devices.json"
    labels_file.write_text(json.dumps({"aa:bb:cc:dd:ee:ff": "Old Label"}))
    inv = DeviceInventory(labels_path=labels_file, cfg=_cfg())

    result = inv.label_device("AA:BB:CC:DD:EE:FF", "New Label")

    assert result["success"] is True
    data = json.loads(labels_file.read_text())
    assert data["aa:bb:cc:dd:ee:ff"] == "New Label"


def test_label_device_invalid_mac(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    result = inv.label_device("not-a-mac", "Xbox")

    assert result["success"] is False
    assert "Invalid MAC" in result["error"]


# --- remove_device_label ---

def test_remove_device_label_success(tmp_path):
    labels_file = tmp_path / "devices.json"
    labels_file.write_text(json.dumps({"aa:bb:cc:dd:ee:ff": "Xbox Series X"}))
    inv = DeviceInventory(labels_path=labels_file, cfg=_cfg())

    result = inv.remove_device_label("AA:BB:CC:DD:EE:FF")

    assert result["success"] is True
    assert result["mac"] == "aa:bb:cc:dd:ee:ff"
    data = json.loads(labels_file.read_text())
    assert "aa:bb:cc:dd:ee:ff" not in data


def test_remove_device_label_not_found(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    result = inv.remove_device_label("AA:BB:CC:DD:EE:FF")

    assert result["success"] is False
    assert "No label found" in result["error"]


def test_remove_device_label_invalid_mac(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    result = inv.remove_device_label("not-a-mac")

    assert result["success"] is False
    assert "Invalid MAC" in result["error"]


# --- _load_labels ---

def test_load_labels_missing_file(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    assert inv._load_labels() == {}


def test_load_labels_existing_file(tmp_path):
    labels_file = tmp_path / "devices.json"
    labels_file.write_text(json.dumps({"aa:bb:cc:dd:ee:ff": "Xbox"}))
    inv = DeviceInventory(labels_path=labels_file, cfg=_cfg())
    assert inv._load_labels() == {"aa:bb:cc:dd:ee:ff": "Xbox"}


# --- _parse_arp_cache ---

ARP_OUTPUT = """\
router.local (192.168.0.1) at a8:9:2:11:22:33 on en0 ifscope [ethernet]
? (192.168.0.50) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]
? (192.168.0.200) at (incomplete) on en0 ifscope [ethernet]
? (192.168.0.255) at ff:ff:ff:ff:ff:ff on en0 ifscope [ethernet]
"""


def test_parse_arp_cache_returns_devices(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=ARP_OUTPUT, stderr="")

    with patch("subprocess.run", return_value=mock_result):
        devices = inv._parse_arp_cache()

    ips = [d["ip"] for d in devices]
    assert "192.168.0.1" in ips
    assert "192.168.0.50" in ips
    # incomplete entries should be excluded
    assert "192.168.0.200" not in ips


def test_parse_arp_cache_empty(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    with patch("subprocess.run", return_value=mock_result):
        devices = inv._parse_arp_cache()

    assert devices == []


# --- _lookup_vendor ---

def test_lookup_vendor_found(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())

    with patch("src.tools.devices._mac_lookup.lookup", return_value="Microsoft Corporation"):
        vendor = inv._lookup_vendor("aa:bb:cc:dd:ee:ff")

    assert vendor == "Microsoft Corporation"


def test_lookup_vendor_not_found(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())

    with patch("src.tools.devices._mac_lookup.lookup", side_effect=Exception("not found")):
        vendor = inv._lookup_vendor("aa:bb:cc:dd:ee:ff")

    assert vendor is None


# --- _enrich_pihole ---

def test_enrich_pihole_adds_fields(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    devices = {
        "192.168.0.50": {
            "ip": "192.168.0.50", "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": None, "pihole_queries_today": None, "pihole_last_seen": None,
        }
    }

    with patch("src.tools.devices.PiholeClient") as MockPihole:
        MockPihole.return_value.get_clients.return_value = {
            "success": True,
            "clients": [
                {"ip": "192.168.0.50", "hostname": "xbox", "query_count": 142, "last_query": 1717330200}
            ],
        }
        inv._enrich_pihole(devices)

    assert devices["192.168.0.50"]["hostname"] == "xbox"
    assert devices["192.168.0.50"]["pihole_queries_today"] == 142
    assert devices["192.168.0.50"]["pihole_last_seen"] is not None


def test_enrich_pihole_unavailable(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    devices = {
        "192.168.0.50": {
            "ip": "192.168.0.50", "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": None, "pihole_queries_today": None, "pihole_last_seen": None,
        }
    }

    with patch("src.tools.devices.PiholeClient") as MockPihole:
        MockPihole.return_value.get_clients.return_value = {"success": False, "error": "unreachable"}
        inv._enrich_pihole(devices)

    # Fields remain None — no crash
    assert devices["192.168.0.50"]["hostname"] is None
    assert devices["192.168.0.50"]["pihole_queries_today"] is None


# --- _enrich_deco ---

def test_enrich_deco_marks_deco_nodes(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    devices = {
        "192.168.0.100": {
            "ip": "192.168.0.100", "mac": "aa:bb:cc:dd:ee:ff",
            "deco_node": None, "deco_signal_dbm": None, "connection_type": None,
        }
    }

    with patch("src.tools.devices.DecoClient") as MockDeco:
        MockDeco.return_value.get_mesh_health.return_value = {
            "success": True,
            "nodes": [
                {"ip": "192.168.0.100", "nickname": "Office", "signal_level_dbm": None, "is_primary": True}
            ],
        }
        inv._enrich_deco(devices)

    assert devices["192.168.0.100"]["deco_node"] == "Office"
    assert devices["192.168.0.100"]["connection_type"] == "deco_node"


def test_enrich_deco_unavailable(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    devices = {
        "192.168.0.100": {
            "ip": "192.168.0.100", "mac": "aa:bb:cc:dd:ee:ff",
            "deco_node": None, "deco_signal_dbm": None, "connection_type": None,
        }
    }

    with patch("src.tools.devices.DecoClient") as MockDeco:
        MockDeco.return_value.get_mesh_health.return_value = {"success": False, "error": "unreachable"}
        inv._enrich_deco(devices)

    # Fields remain None — no crash
    assert devices["192.168.0.100"]["deco_node"] is None


# --- _ping_sweep ---

def test_ping_sweep_pings_subnet(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    pinged = []

    def fake_ping(args, **kwargs):
        pinged.append(args[-1])  # last arg is the IP
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_ping):
        inv._ping_sweep()

    assert "192.168.0.1" in pinged
    assert "192.168.0.254" in pinged
    assert len(pinged) == 254


# --- get_network_devices ---

def test_get_network_devices_fast_scan(tmp_path):
    labels_file = tmp_path / "devices.json"
    labels_file.write_text(json.dumps({"aa:bb:cc:dd:ee:ff": "Xbox Series X"}))
    inv = DeviceInventory(labels_path=labels_file, cfg=_cfg())

    arp_result = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout="? (192.168.0.50) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]\n",
        stderr="",
    )

    with patch("subprocess.run", return_value=arp_result), \
         patch("src.tools.devices._mac_lookup.lookup", return_value="Microsoft Corporation"), \
         patch("src.tools.devices.PiholeClient") as MockPihole, \
         patch("src.tools.devices.DecoClient") as MockDeco:

        MockPihole.return_value.get_clients.return_value = {"success": False, "error": "offline"}
        MockDeco.return_value.get_mesh_health.return_value = {"success": False, "error": "offline"}

        result = inv.get_network_devices(deep_scan=False)

    assert result["success"] is True
    assert result["deep_scan"] is False
    assert result["device_count"] == 1
    device = result["devices"][0]
    assert device["ip"] == "192.168.0.50"
    assert device["mac"] == "aa:bb:cc:dd:ee:ff"
    assert device["label"] == "Xbox Series X"
    assert device["vendor"] == "Microsoft Corporation"
    assert device["online"] is True


def test_get_network_devices_deep_scan_triggers_sweep(tmp_path):
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())
    ping_calls = []

    def fake_run(args, **kwargs):
        if args[0] == 'ping':
            ping_calls.append(args[-1])
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run), \
         patch("src.tools.devices.PiholeClient") as MockPihole, \
         patch("src.tools.devices.DecoClient") as MockDeco:

        MockPihole.return_value.get_clients.return_value = {"success": False}
        MockDeco.return_value.get_mesh_health.return_value = {"success": False}

        result = inv.get_network_devices(deep_scan=True)

    assert result["success"] is True
    assert result["deep_scan"] is True
    assert len(ping_calls) == 254


def test_get_network_devices_partial_enrichment(tmp_path):
    """Pi-hole and Deco both offline — still returns ARP devices with success=True."""
    inv = DeviceInventory(labels_path=tmp_path / "devices.json", cfg=_cfg())

    arp_result = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout="? (192.168.0.50) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]\n",
        stderr="",
    )

    with patch("subprocess.run", return_value=arp_result), \
         patch("src.tools.devices._mac_lookup.lookup", side_effect=Exception("no vendor")), \
         patch("src.tools.devices.PiholeClient") as MockPihole, \
         patch("src.tools.devices.DecoClient") as MockDeco:

        MockPihole.return_value.get_clients.return_value = {"success": False}
        MockDeco.return_value.get_mesh_health.return_value = {"success": False}

        result = inv.get_network_devices()

    assert result["success"] is True
    device = result["devices"][0]
    assert device["hostname"] is None
    assert device["vendor"] is None
    assert device["pihole_queries_today"] is None
    assert device["deco_node"] is None
