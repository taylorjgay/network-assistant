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
