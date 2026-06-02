from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.config import load_config
from src.tools.diagnostics import (
    ping_host as _ping_host,
    traceroute_host as _traceroute_host,
    run_speedtest as _run_speedtest,
    test_dns_resolution as _test_dns_resolution,
)
from src.tools.er605 import ER605Client
from src.tools.deco import DecoClient
from src.tools.pihole import PiholeClient

mcp = FastMCP("NetworkAssistant")

_config_path = Path(__file__).parent.parent / "config.json"
_cfg = load_config(_config_path) if _config_path.exists() else None

_er605 = ER605Client(**vars(_cfg.er605)) if _cfg else None
_deco = DecoClient(**vars(_cfg.deco)) if _cfg else None

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


if __name__ == "__main__":
    mcp.run()
