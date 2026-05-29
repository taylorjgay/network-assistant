import src.server as server_module

EXPECTED_TOOLS = [
    "get_wan_status",
    "get_router_info",
    "get_connected_clients",
    "get_mesh_health",
    "get_pihole_stats",
    "test_dns_resolution",
    "ping_host",
    "traceroute_host",
    "run_speedtest",
]


def test_server_has_name():
    assert server_module.mcp.name == "NetworkAssistant"


def test_all_tools_are_callable():
    for name in EXPECTED_TOOLS:
        assert callable(getattr(server_module, name, None)), f"Tool '{name}' not found in server module"
