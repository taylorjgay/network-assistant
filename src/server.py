from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config import load_config
from src import api
from src.tools.diagnostics import (
    ping_host as _ping_host,
    traceroute_host as _traceroute_host,
    run_speedtest as _run_speedtest,
    test_dns_resolution as _test_dns_resolution,
)
from src.tools.er605 import ER605Client
from src.tools.deco import DecoClient
from src.tools.pihole import PiholeClient
from src.tools.devices import DeviceInventory
from src.tools.wan_health import WANHealthClient
from src.tools.upnp import get_upnp_status as _get_upnp_status, get_upnp_portmaps as _get_upnp_portmaps
from src.tools.wan_speed import WANSpeedClient

mcp = FastMCP("NetworkAssistant")

_config_path = Path(__file__).parent.parent / "config.json"
_cfg = load_config(_config_path) if _config_path.exists() else None

_er605 = ER605Client(**vars(_cfg.er605)) if _cfg else None
_wan_health = WANHealthClient(**vars(_cfg.er605)) if _cfg else None
_deco = DecoClient(**vars(_cfg.deco)) if _cfg else None
_devices_labels_path = Path(__file__).parent.parent / "devices.json"
_devices = DeviceInventory(labels_path=_devices_labels_path, cfg=_cfg)

_NO_CONFIG = {"success": False, "error": "config.json not found",
              "suggestion": "Copy config.example.json to config.json and fill in your device details",
              "attempted": "n/a — no config.json"}


@mcp.tool()
def get_wan_status() -> dict:
    """Get ER605 WAN status: active interface, public IP, uptime, failover state."""
    return _er605.get_wan_status() if _er605 else _NO_CONFIG


@mcp.tool()
def get_router_info() -> dict:
    """Get ER605 model, firmware version, and system uptime."""
    return _er605.get_router_info() if _er605 else _NO_CONFIG


@mcp.tool()
def get_wan_policy() -> dict:
    """Get ER605 WAN failover policy: mode (failover/load_balance), primary WAN, health check settings."""
    return _er605.get_wan_policy() if _er605 else _NO_CONFIG


@mcp.tool()
def set_wan_priority(primary_wan: str, dry_run: bool = False) -> dict:
    """Force ER605 to use a specific WAN. primary_wan: 'WAN1', 'WAN2', or 'auto' (restore automatic failover). dry_run=True shows what would be sent without applying it."""
    return _er605.set_wan_priority(primary_wan, dry_run=dry_run) if _er605 else _NO_CONFIG


@mcp.tool()
def get_wan_health() -> dict:
    """Get WAN health: per-interface link status for both WANs plus active latency/packet-loss probe. Sets degraded=True when packet loss >5% or latency >150ms."""
    if not _wan_health:
        return _NO_CONFIG
    return _wan_health.get_wan_health()


@mcp.tool()
def compare_wan_health() -> dict:
    """Compare WAN1 vs WAN2 health by briefly routing through each. WARNING: temporarily disrupts new outbound connections for ~4 seconds total. Only call when investigating suspected WAN degradation."""
    if not _wan_health:
        return _NO_CONFIG
    return _wan_health.compare_wan_health()


@mcp.tool()
def get_port_forwards() -> dict:
    """List all ER605 port forwarding (virtual server) rules: name, external port, internal IP/port, protocol."""
    return _er605.get_port_forwards() if _er605 else _NO_CONFIG


@mcp.tool()
def add_port_forward(
    name: str,
    external_port: int,
    internal_ip: str,
    internal_port: int,
    protocol: str = "tcp",
    dry_run: bool = False,
) -> dict:
    """Add an ER605 port forward rule. protocol: 'tcp', 'udp', or 'both'. dry_run=True shows payload without applying."""
    return _er605.add_port_forward(name, external_port, internal_ip, internal_port, protocol=protocol, dry_run=dry_run) if _er605 else _NO_CONFIG


@mcp.tool()
def remove_port_forward(rule_id: str, dry_run: bool = False) -> dict:
    """Remove an ER605 port forward rule by ID (get IDs from get_port_forwards). dry_run=True shows payload without applying."""
    return _er605.remove_port_forward(rule_id, dry_run=dry_run) if _er605 else _NO_CONFIG


@mcp.tool()
def get_firewall_rules() -> dict:
    """List all ER605 firewall ACL rules: name, source IP, destination IP, action (allow/deny), protocol."""
    return _er605.get_firewall_rules() if _er605 else _NO_CONFIG


@mcp.tool()
def add_firewall_rule(
    name: str,
    src_ip: str = "",
    dst_ip: str = "",
    action: str = "deny",
    protocol: str = "all",
    dry_run: bool = False,
) -> dict:
    """Add an ER605 firewall ACL rule. action: 'deny' or 'allow'. protocol: 'tcp', 'udp', 'icmp', or 'all'. Empty src_ip/dst_ip means any. dry_run=True shows payload without applying."""
    return _er605.add_firewall_rule(name, src_ip=src_ip, dst_ip=dst_ip, action=action, protocol=protocol, dry_run=dry_run) if _er605 else _NO_CONFIG


@mcp.tool()
def remove_firewall_rule(rule_id: str, dry_run: bool = False) -> dict:
    """Remove an ER605 firewall ACL rule by ID (get IDs from get_firewall_rules). dry_run=True shows payload without applying."""
    return _er605.remove_firewall_rule(rule_id, dry_run=dry_run) if _er605 else _NO_CONFIG


@mcp.tool()
def get_network_devices(deep_scan: bool = False) -> dict:
    """Get all devices on 192.168.0.x: IP, MAC, label, hostname, vendor, Pi-hole stats, Deco node info. deep_scan=True pings all 254 hosts first (~15s) to find idle devices."""
    return _devices.get_network_devices(deep_scan=deep_scan)


@mcp.tool()
def label_device(mac: str, label: str) -> dict:
    """Assign a friendly name to a device by MAC address (e.g. 'AA:BB:CC:DD:EE:FF', 'Xbox Series X'). Labels persist in devices.json."""
    return _devices.label_device(mac, label)


@mcp.tool()
def remove_device_label(mac: str) -> dict:
    """Remove a device label by MAC address. Use get_network_devices to find MACs."""
    return _devices.remove_device_label(mac)


@mcp.tool()
def get_connected_clients() -> dict:
    """Get all devices on the Deco mesh: hostname, IP, MAC, which node, band."""
    if not _cfg:
        return _NO_CONFIG
    return DecoClient(**vars(_cfg.deco)).get_connected_clients()


@mcp.tool()
def get_mesh_health() -> dict:
    """Get Deco node status: online/offline, wired vs wireless backhaul, signal strength."""
    if not _cfg:
        return _NO_CONFIG
    return DecoClient(**vars(_cfg.deco)).get_mesh_health()


@mcp.tool()
def get_pihole_stats() -> dict:
    """Get Pi-hole query stats: total queries, blocked count, block percentage, enabled state."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_pihole_stats()


@mcp.tool()
def get_query_log(
    blocked: bool | None = None,
    domain: str | None = None,
    client: str | None = None,
    limit: int = 50,
) -> dict:
    """Get recent DNS query log. Filter by blocked=True for only blocked queries, domain or client for specific lookups."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_query_log(blocked=blocked, domain=domain, client=client, limit=limit)


@mcp.tool()
def get_top_domains(blocked: bool = False, count: int = 10) -> dict:
    """Get top queried domains. Set blocked=True for top blocked domains."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_top_domains(blocked=blocked, count=count)


@mcp.tool()
def get_top_clients(count: int = 10) -> dict:
    """Get the top N clients ranked by DNS query volume today (default top 10)."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_top_clients(count=count)


@mcp.tool()
def get_domain_lists() -> dict:
    """Get all Pi-hole allowlist and blocklist entries (exact and regex)."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_domain_lists()


@mcp.tool()
def get_clients() -> dict:
    """Get all known network clients Pi-hole has seen, with IP, hostname, total query count, and last seen time."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_clients()


@mcp.tool()
def get_pihole_system() -> dict:
    """Get Pi-hole system info: CPU load, RAM usage, uptime, hostname."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_pihole_system()


@mcp.tool()
def add_domain(
    domain: str,
    list_type: str = "block",
    kind: str = "exact",
    comment: str = "",
) -> dict:
    """Add a domain to Pi-hole's allowlist or blocklist. list_type: 'allow' or 'block'. kind: 'exact' or 'regex'."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).add_domain(domain, list_type=list_type, kind=kind, comment=comment)


@mcp.tool()
def remove_domain(
    domain: str,
    list_type: str = "block",
    kind: str = "exact",
) -> dict:
    """Remove a domain from Pi-hole's allowlist or blocklist."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).remove_domain(domain, list_type=list_type, kind=kind)


@mcp.tool()
def set_blocking(enabled: bool, timer: int | None = None) -> dict:
    """Enable or disable Pi-hole ad blocking. Optionally set timer (seconds) to auto-re-enable."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).set_blocking(enabled=enabled, timer=timer)


@mcp.tool()
def update_gravity() -> dict:
    """Trigger a Pi-hole gravity update to refresh blocklists. Runs asynchronously on the Pi."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).update_gravity()


@mcp.tool()
def get_query_trends() -> dict:
    """Get 24 hours of hourly DNS query volume (total + blocked per hour) and flag spike hours (>2× average)."""
    if not _cfg:
        return _NO_CONFIG
    return PiholeClient(**vars(_cfg.pihole)).get_query_trends()


@mcp.tool()
def test_dns_resolution(hostname: str, dns_server: str | None = None) -> dict:
    """Resolve a hostname and report which DNS server answered and the resolved IPs.
    Optionally specify dns_server (e.g. '8.8.8.8') to bypass Pi-hole."""
    return _test_dns_resolution(hostname, dns_server)


@mcp.tool()
def ping_host(host: str, count: int = 4) -> dict:
    """Ping a host and return latency and packet loss. Works for LAN and internet hosts."""
    return _ping_host(host, count)


@mcp.tool()
def traceroute_host(host: str) -> dict:
    """Traceroute to a host showing each hop and its latency."""
    return _traceroute_host(host)


@mcp.tool()
def run_speedtest() -> dict:
    """Run an internet speed test and return download Mbps, upload Mbps, and ping."""
    return _run_speedtest()


@mcp.tool()
def get_upnp_status() -> dict:
    """Get UPnP gateway status: whether UPnP is available, external IP, and connection state."""
    return _get_upnp_status()


@mcp.tool()
def get_upnp_portmaps() -> dict:
    """List all active UPnP port mappings registered by LAN devices (e.g. Xbox, Switch)."""
    return _get_upnp_portmaps()


@mcp.tool()
def compare_wan_speed(quick: bool = False) -> dict:
    """Compare WAN1 vs WAN2 speed and latency. quick=True runs a fast latency-only check (~15s); quick=False runs a full Ookla speedtest (~2-3 min). Returns side-by-side results and a recommendation."""
    cfg = load_config(_config_path)
    return WANSpeedClient(**vars(cfg.er605)).compare_wan_speed(quick=quick)


# ── REST API routes ──────────────────────────────────────────────────────────

@mcp.custom_route("/api/hosts", methods=["GET"])
async def _api_hosts(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.get_hosts(_cfg))


@mcp.custom_route("/api/snapshot", methods=["GET"])
async def _api_snapshot(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.snapshot(_cfg))


@mcp.custom_route("/api/wan", methods=["GET"])
async def _api_wan(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.wan_health(_cfg))


@mcp.custom_route("/api/wan/priority", methods=["POST"])
async def _api_wan_priority(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)
    return JSONResponse(await api.set_wan_priority(_cfg, body.get("primary_wan", "auto")))


@mcp.custom_route("/api/wan/compare", methods=["POST"])
async def _api_wan_compare(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.wan_compare(_cfg))


@mcp.custom_route("/api/pihole/stats", methods=["GET"])
async def _api_pihole_stats(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.pihole_stats(_cfg))


@mcp.custom_route("/api/pihole/trends", methods=["GET"])
async def _api_pihole_trends(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.pihole_trends(_cfg))


@mcp.custom_route("/api/pihole/top-domains", methods=["GET"])
async def _api_pihole_top_domains(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.pihole_top_domains(_cfg))


@mcp.custom_route("/api/pihole/system", methods=["GET"])
async def _api_pihole_system(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.pihole_system(_cfg))


@mcp.custom_route("/api/pihole/blocking", methods=["POST"])
async def _api_pihole_blocking(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)
    return JSONResponse(await api.set_pihole_blocking(_cfg, bool(body.get("enabled", True))))


@mcp.custom_route("/api/mesh", methods=["GET"])
async def _api_mesh(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.mesh_health(_cfg))


@mcp.custom_route("/api/devices", methods=["GET"])
async def _api_devices(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.get_devices(_cfg))


@mcp.custom_route("/api/devices/scan", methods=["POST"])
async def _api_devices_scan(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.get_devices(_cfg, deep_scan=True))


@mcp.custom_route("/api/devices/{mac}/label", methods=["POST", "DELETE"])
async def _api_device_label(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    mac = request.path_params["mac"]
    if request.method == "DELETE":
        return JSONResponse(await api.do_remove_label(_cfg, mac))
    body = await request.json()
    label = body.get("label", "").strip()
    if not label:
        return JSONResponse({"success": False, "error": "label is required"}, status_code=400)
    return JSONResponse(await api.do_label_device(_cfg, mac, label))


@mcp.custom_route("/api/upnp", methods=["GET"])
async def _api_upnp(request: Request) -> JSONResponse:
    # UPnP uses SSDP discovery — no credentials needed
    return JSONResponse(await api.upnp())


@mcp.custom_route("/api/ports", methods=["GET", "POST"])
async def _api_ports(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    if request.method == "POST":
        try:
            body = await request.json()
            name = body["name"]
            external_port = int(body["external_port"])
            internal_ip = body["internal_ip"]
            internal_port = int(body["internal_port"])
        except (KeyError, TypeError, ValueError) as exc:
            return JSONResponse({"success": False, "error": f"Bad request: {exc}"}, status_code=400)
        return JSONResponse(await api.do_add_port_forward(
            _cfg, name, external_port, internal_ip, internal_port,
            body.get("protocol", "tcp"),
        ))
    return JSONResponse(await api.get_port_forwards(_cfg))


@mcp.custom_route("/api/ports/{rule_id}", methods=["DELETE"])
async def _api_ports_remove(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.do_remove_port_forward(_cfg, request.path_params["rule_id"]))


@mcp.custom_route("/api/diagnostics/ping", methods=["POST"])
async def _api_ping(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    try:
        body = await request.json()
        host = body.get("host", "").strip()
        if not host:
            return JSONResponse({"success": False, "error": "host is required"}, status_code=400)
        count = max(1, min(20, int(body.get("count", 4))))
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)
    return JSONResponse(await api.diag_ping(host, count))


@mcp.custom_route("/api/diagnostics/traceroute", methods=["POST"])
async def _api_traceroute(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    try:
        body = await request.json()
        host = body.get("host", "").strip()
        if not host:
            return JSONResponse({"success": False, "error": "host is required"}, status_code=400)
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)
    return JSONResponse(await api.diag_traceroute(host))


@mcp.custom_route("/api/diagnostics/speedtest", methods=["POST"])
async def _api_speedtest(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.diag_speedtest())


@mcp.custom_route("/api/diagnostics/dns", methods=["POST"])
async def _api_dns(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    try:
        body = await request.json()
        hostname = body.get("hostname", "").strip()
        if not hostname:
            return JSONResponse({"success": False, "error": "hostname is required"}, status_code=400)
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)
    return JSONResponse(await api.diag_dns(hostname))


# Must be last — catch-all for React SPA
@mcp.custom_route("/{path:path}", methods=["GET"])
async def _serve_static(request: Request) -> Response:
    return await api.serve_static(request)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
