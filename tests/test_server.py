import src.server as server_module

EXPECTED_TOOLS = [
    "get_wan_status", "get_router_info",
    "get_wan_policy", "set_wan_priority",
    "get_port_forwards", "add_port_forward", "remove_port_forward",
    "get_firewall_rules", "add_firewall_rule", "remove_firewall_rule",
    "get_connected_clients", "get_mesh_health",
    "get_pihole_stats", "get_query_log", "get_top_domains", "get_top_clients",
    "get_domain_lists", "get_clients", "get_pihole_system", "add_domain",
    "remove_domain", "set_blocking", "update_gravity",
    "test_dns_resolution", "ping_host", "traceroute_host", "run_speedtest",
]


def test_server_has_name():
    assert server_module.mcp.name == "NetworkAssistant"


def test_all_tools_are_callable():
    for name in EXPECTED_TOOLS:
        assert callable(getattr(server_module, name, None)), f"Tool '{name}' not found in server module"
