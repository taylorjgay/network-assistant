import json
import pytest
from pathlib import Path
from types import SimpleNamespace

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
