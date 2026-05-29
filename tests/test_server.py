import importlib
import src.server as server_module


def test_server_has_name():
    assert server_module.mcp.name == "NetworkAssistant"


def test_server_module_imports_without_error():
    # Verifies no import-time side effects crash on missing config.json
    assert server_module is not None
