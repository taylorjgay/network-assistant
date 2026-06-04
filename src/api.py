import asyncio
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from src.config import Config
from src.tools.deco import DecoClient
from src.tools.devices import DeviceInventory
from src.tools.er605 import ER605Client
from src.tools.pihole import PiholeClient
from src.tools.upnp import get_upnp_portmaps, get_upnp_status
from src.tools.wan_health import WANHealthClient

_LABELS_PATH = Path(__file__).parent.parent / "devices.json"
_DIST = Path(__file__).parent.parent / "dashboard" / "dist"


async def snapshot(cfg: Config) -> dict:
    wan, pihole, mesh, router = await asyncio.gather(
        asyncio.to_thread(WANHealthClient(**vars(cfg.er605)).get_wan_health),
        asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_pihole_stats),
        asyncio.to_thread(DecoClient(**vars(cfg.deco)).get_mesh_health),
        asyncio.to_thread(ER605Client(**vars(cfg.er605)).get_router_info),
        return_exceptions=True,
    )
    return {
        "wan": wan if not isinstance(wan, Exception) else {"success": False, "error": str(wan)},
        "pihole": pihole if not isinstance(pihole, Exception) else {"success": False, "error": str(pihole)},
        "mesh": mesh if not isinstance(mesh, Exception) else {"success": False, "error": str(mesh)},
        "router": router if not isinstance(router, Exception) else {"success": False, "error": str(router)},
    }


async def wan_health(cfg: Config) -> dict:
    return await asyncio.to_thread(WANHealthClient(**vars(cfg.er605)).get_wan_health)


async def wan_compare(cfg: Config) -> dict:
    return await asyncio.to_thread(WANHealthClient(**vars(cfg.er605)).compare_wan_health)


async def set_wan_priority(cfg: Config, primary_wan: str) -> dict:
    return await asyncio.to_thread(ER605Client(**vars(cfg.er605)).set_wan_priority, primary_wan)


async def pihole_stats(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_pihole_stats)


async def pihole_trends(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_query_trends)


async def pihole_top_domains(cfg: Config) -> dict:
    queried, blocked = await asyncio.gather(
        asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_top_domains, False),
        asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_top_domains, True),
    )
    return {"queried": queried, "blocked": blocked}


async def pihole_system(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_pihole_system)


async def set_pihole_blocking(cfg: Config, enabled: bool) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).set_blocking, enabled)


async def mesh_health(cfg: Config) -> dict:
    return await asyncio.to_thread(DecoClient(**vars(cfg.deco)).get_mesh_health)


async def get_devices(cfg: Config, deep_scan: bool = False) -> dict:
    inventory = DeviceInventory(labels_path=_LABELS_PATH, cfg=cfg)
    return await asyncio.to_thread(inventory.get_network_devices, deep_scan)


async def do_label_device(cfg: Config, mac: str, label: str) -> dict:
    inventory = DeviceInventory(labels_path=_LABELS_PATH, cfg=cfg)
    return await asyncio.to_thread(inventory.label_device, mac, label)


async def do_remove_label(cfg: Config, mac: str) -> dict:
    inventory = DeviceInventory(labels_path=_LABELS_PATH, cfg=cfg)
    return await asyncio.to_thread(inventory.remove_device_label, mac)


async def upnp() -> dict:
    status, portmaps = await asyncio.gather(
        asyncio.to_thread(get_upnp_status),
        asyncio.to_thread(get_upnp_portmaps),
    )
    return {"status": status, "portmaps": portmaps}


async def get_port_forwards(cfg: Config) -> dict:
    return await asyncio.to_thread(ER605Client(**vars(cfg.er605)).get_port_forwards)


async def do_add_port_forward(
    cfg: Config,
    name: str,
    external_port: int,
    internal_ip: str,
    internal_port: int,
    protocol: str,
) -> dict:
    return await asyncio.to_thread(
        ER605Client(**vars(cfg.er605)).add_port_forward,
        name, external_port, internal_ip, internal_port,
        protocol=protocol, dry_run=False,
    )


async def do_remove_port_forward(cfg: Config, rule_id: str) -> dict:
    return await asyncio.to_thread(ER605Client(**vars(cfg.er605)).remove_port_forward, rule_id)


async def serve_static(request: Request) -> Response:
    path = request.path_params.get("path", "") or "index.html"
    if not _DIST.exists():
        return JSONResponse(
            {"error": "Dashboard not built. Run: cd dashboard && npm run build"},
            status_code=503,
        )
    file_path = _DIST / path
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    index = _DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"error": "Not found"}, status_code=404)
