from __future__ import annotations

DISCOVER_DELAY_MS = 2000


def _discover():
    """Return an initialised UPnP IGD object, or None if no gateway found."""
    import miniupnpc
    u = miniupnpc.UPnP()
    u.discoverdelay = DISCOVER_DELAY_MS
    try:
        n = u.discover()
    except Exception:
        # miniupnpc raises Exception("Success") when no device responds to SSDP
        return None
    if n == 0:
        return None
    u.selectigd()
    return u


def get_upnp_status() -> dict:
    """Return UPnP gateway status: availability, external IP, connection state."""
    try:
        u = _discover()
        if u is None:
            return {
                "success": True,
                "available": False,
                "error": "No UPnP gateway found on the network",
            }
        status_tuple = u.statusinfo()
        return {
            "success": True,
            "available": True,
            "lan_ip": u.lanaddr,
            "external_ip": u.externalipaddress(),
            "status": status_tuple[0] if status_tuple else "Unknown",
            "connection_type": u.connectiontype(),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "Check UPnP is enabled on ER605"}


def get_upnp_portmaps() -> dict:
    """Return all active UPnP port mappings registered by LAN devices."""
    try:
        u = _discover()
        if u is None:
            return {
                "success": True,
                "available": False,
                "mappings": [],
                "error": "No UPnP gateway found on the network",
            }
        mappings = []
        i = 0
        while True:
            entry = u.getgenericportmapping(i)
            if entry is None:
                break
            # entry: (extPort, proto, (intHost, intPort), desc, enabled, remoteHost, leaseDuration)
            ext_port, proto, (int_host, int_port), desc, enabled, remote_host, lease = entry
            mappings.append({
                "external_port": ext_port,
                "protocol": proto,
                "internal_host": int_host,
                "internal_port": int_port,
                "description": desc,
                "enabled": bool(enabled),
                "remote_host": remote_host or "any",
                "lease_seconds": lease,
            })
            i += 1
        return {
            "success": True,
            "available": True,
            "count": len(mappings),
            "mappings": mappings,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "suggestion": "Check UPnP is enabled on ER605"}
