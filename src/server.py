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
_pihole = PiholeClient(**vars(_cfg.pihole)) if _cfg else None

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
    return _deco.get_connected_clients() if _deco else _NO_CONFIG


@mcp.tool()
def get_mesh_health() -> dict:
    """Get Deco node status: online/offline, wired vs wireless backhaul, signal strength."""
    return _deco.get_mesh_health() if _deco else _NO_CONFIG


@mcp.tool()
def get_pihole_stats() -> dict:
    """Get Pi-hole query stats: total queries, blocked count, block percentage, enabled state."""
    return _pihole.get_pihole_stats() if _pihole else _NO_CONFIG


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
