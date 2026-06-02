# Network Device Inventory — Design Spec

**Date:** 2026-06-02
**Status:** Approved, ready for implementation planning

## Context

The MCP server currently has no unified view of what devices are on the network. The ER605 DHCP lease table is inaccessible (error 1014), Deco's `client_list` crashes on the current firmware, and Pi-hole client data is only useful once DHCP DNS is pointed at it. This spec defines a `get_network_devices` tool that merges four data sources into a unified device list — useful today and richer after DHCP DNS is switched over.

This feature is also the first building block toward a future `get_network_dashboard` tool that aggregates all network health data into a single call.

## Architecture

No new tool files for scanning logic itself — a new `src/tools/devices.py` module contains a `DeviceInventory` class. Labels are stored in `devices.json` in the project root (sibling to `config.json`). Three new MCP tools are registered in `src/server.py`.

```
src/tools/devices.py     — DeviceInventory class (scan + label management)
devices.json             — MAC → label mapping (user-managed, gitignored)
devices.example.json     — example file showing format
```

## Data Sources

`get_network_devices` merges four sources, keyed on IP address:

1. **ARP cache** (`arp -a`) — primary source. Runs instantly, returns IP + MAC for every device the Mac has communicated with recently. Provides the `online` signal and MAC address used to join other sources.

2. **Pi-hole `/api/clients`** — adds `hostname`, `pihole_queries_today`, `pihole_last_seen`. If Pi-hole is unreachable, these fields are `null` per device; the tool proceeds with remaining sources.

3. **Deco `device_list`** — adds `deco_node` (node nickname) and `deco_signal_dbm` for WiFi devices. Wired devices won't appear in Deco's list; `connection_type` is set to `"wired"` for them, `"wifi"` for Deco-matched devices, `"unknown"` otherwise. A fresh `DecoClient` instance is created per call (per existing singleton-bug fix pattern).

4. **`devices.json`** — adds user-defined `label` per MAC address. If the file doesn't exist, labels are simply omitted.

**MAC vendor lookup** uses the `mac-vendor-lookup` Python library (local OUI database, no internet dependency). Added to `requirements.txt`.

## deep_scan Mode

Default (`deep_scan=False`): read ARP cache directly — returns in under 1 second.

With `deep_scan=True`: ping-sweep 192.168.0.1–254 in parallel using a `ThreadPoolExecutor` before reading ARP cache. Timeout 1s per ping. Expected runtime ~15 seconds. Finds devices that have been idle long enough to drop from the ARP cache.

The subnet `192.168.0.0/24` is hardcoded — it matches the network topology and is not configurable in this spec.

## Tool Inventory

### `get_network_devices(deep_scan: bool = False) -> dict`

Returns all discovered devices with enriched metadata.

```python
{
    "success": True,
    "deep_scan": False,
    "device_count": 12,
    "devices": [
        {
            "ip": "192.168.0.50",
            "mac": "AA:BB:CC:DD:EE:FF",
            "label": "Xbox Series X",
            "hostname": "xbox",
            "vendor": "Microsoft Corporation",
            "online": True,
            "pihole_queries_today": 142,
            "pihole_last_seen": "2026-06-02T14:30:00",
            "deco_node": "Basement",
            "deco_signal_dbm": -60,
            "connection_type": "wifi"
        },
        ...
    ]
}
```

Fields are `null` when the data source is unavailable or the device wasn't found in that source.

### `label_device(mac: str, label: str) -> dict`

Writes or updates a label for a device in `devices.json`. MAC address is normalized to lowercase colon-separated format before writing.

```python
# Success
{"success": True, "mac": "aa:bb:cc:dd:ee:ff", "label": "Xbox Series X"}

# Error (invalid MAC format)
{"success": False, "error": "Invalid MAC address format", "suggestion": "Use format AA:BB:CC:DD:EE:FF"}
```

### `remove_device_label(mac: str) -> dict`

Removes a label entry from `devices.json`.

```python
# Success
{"success": True, "mac": "aa:bb:cc:dd:ee:ff"}

# Error (MAC not found)
{"success": False, "error": "No label found for aa:bb:cc:dd:ee:ff", "suggestion": "Use label_device to add a label first"}
```

## `devices.json` Format

```json
{
  "aa:bb:cc:dd:ee:ff": "Xbox Series X",
  "11:22:33:44:55:66": "Switch 2",
  "aa:bb:cc:dd:ee:00": "Raspberry Pi (Pi-hole)"
}
```

`devices.json` is gitignored (contains user data). `devices.example.json` is committed showing the format.

## Error Handling

- **ARP parse failure**: return `{"success": False, "error": "...", "suggestion": "Check that 'arp' is available on PATH"}`
- **Pi-hole unavailable**: proceed, all Pi-hole fields are `null`
- **Deco unavailable**: proceed, all Deco fields are `null`
- **`devices.json` missing**: proceed, all labels are `null` (not an error)
- **`mac-vendor-lookup` lookup miss**: `vendor` is `null` (not an error)

The tool never fails completely unless ARP itself fails.

## Testing

Follow existing patterns in `tests/`. Mock `subprocess.run` for ARP output. Mock Pi-hole and Deco HTTP calls with `respx`. Test `devices.json` read/write with a temp file.

Each tool gets:
- **Success path** — all four sources return data, verify merged output
- **Partial degradation** — Pi-hole unavailable, Deco unavailable (fields null, success still True)
- **deep_scan path** — verify ping sweep is triggered, mock subprocess
- **label_device** — write new label, overwrite existing label, invalid MAC format
- **remove_device_label** — remove existing, attempt to remove nonexistent

~15 new tests.

## Dependencies

- `mac-vendor-lookup` — add to `requirements.txt`

## What's Not In Scope

- Configurable subnet (hardcoded 192.168.0.0/24)
- Historical device tracking / "new device" alerts (future feature)
- Network dashboard aggregator (separate future spec)
- Port scanning or service detection per device
