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
from src.tools.diagnostics import (
    ping_host as _ping_host,
    traceroute_host as _traceroute_host,
    run_speedtest as _run_speedtest,
    test_dns_resolution as _test_dns_resolution,
)
from src.tools.wan_health import WANHealthClient
from src.tools.wan_speed import WANSpeedClient

_LABELS_PATH = Path(__file__).parent.parent / "devices.json"
_DIST = Path(__file__).parent.parent / "dashboard" / "dist"


async def snapshot(cfg: Config) -> dict:
    # ER605 rejects concurrent logins from the same IP — run wan+router sequentially.
    # Pi-hole and Deco hit different devices so they run in parallel with ER605.
    async def _er605_sequential():
        w = await asyncio.to_thread(WANHealthClient(**vars(cfg.er605)).get_wan_health)
        r = await asyncio.to_thread(ER605Client(**vars(cfg.er605)).get_router_info)
        return w, r

    async def _pihole_data():
        stats, sys_info = await asyncio.gather(
            asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_pihole_stats),
            asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_pihole_system),
            return_exceptions=True,
        )
        if not isinstance(sys_info, BaseException) and sys_info.get("success"):
            for key in ("cpu_percent", "mem_percent", "uptime_seconds", "hostname"):
                if not isinstance(stats, BaseException) and key in sys_info:
                    stats[key] = sys_info[key]
        return stats

    er605_result, pihole, mesh = await asyncio.gather(
        _er605_sequential(),
        _pihole_data(),
        asyncio.to_thread(DecoClient(**vars(cfg.deco)).get_mesh_health),
        return_exceptions=True,
    )

    if isinstance(er605_result, BaseException):
        err = {"success": False, "error": str(er605_result)}
        wan, router = err, err
    else:
        wan, router = er605_result

    return {
        "wan": wan if not isinstance(wan, BaseException) else {"success": False, "error": str(wan)},
        "pihole": pihole if not isinstance(pihole, BaseException) else {"success": False, "error": str(pihole)},
        "mesh": mesh if not isinstance(mesh, BaseException) else {"success": False, "error": str(mesh)},
        "router": router if not isinstance(router, BaseException) else {"success": False, "error": str(router)},
    }


async def get_hosts(cfg: Config) -> dict:
    return {
        "router": f"https://{cfg.er605.host}/webpages/login.html",
        "deco": f"http://{cfg.deco.host}/webpages/index.html",
        "pihole": "http://pi.hole/admin/login",
    }


async def wan_health(cfg: Config) -> dict:
    return await asyncio.to_thread(WANHealthClient(**vars(cfg.er605)).get_wan_health)


async def wan_compare(cfg: Config) -> dict:
    return await asyncio.to_thread(WANHealthClient(**vars(cfg.er605)).compare_wan_health)


async def set_wan_priority(cfg: Config, primary_wan: str) -> dict:
    return await asyncio.to_thread(
        ER605Client(**vars(cfg.er605)).set_wan_priority, primary_wan, dry_run=False
    )


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
        return_exceptions=True,
    )
    return {
        "status": status if not isinstance(status, BaseException) else {"success": False, "error": str(status)},
        "portmaps": portmaps if not isinstance(portmaps, BaseException) else {"success": False, "error": str(portmaps), "mappings": []},
    }


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
    return await asyncio.to_thread(
        ER605Client(**vars(cfg.er605)).remove_port_forward, rule_id, dry_run=False
    )


async def diag_ping(host: str, count: int = 4) -> dict:
    return await asyncio.to_thread(_ping_host, host, count)


async def diag_traceroute(host: str) -> dict:
    return await asyncio.to_thread(_traceroute_host, host)


async def diag_speedtest() -> dict:
    return await asyncio.to_thread(_run_speedtest)


async def diag_dns(hostname: str) -> dict:
    return await asyncio.to_thread(_test_dns_resolution, hostname)


async def wan_speed_compare(cfg: Config, quick: bool = True) -> dict:
    return await asyncio.to_thread(WANSpeedClient(**vars(cfg.er605)).compare_wan_speed, quick)


async def pihole_gravity(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).update_gravity)


async def pihole_top_clients(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_top_clients)


async def pihole_clients(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_clients)


async def pihole_domains(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_domain_lists)


async def pihole_add_domain(cfg: Config, domain: str, list_type: str, kind: str) -> dict:
    return await asyncio.to_thread(
        PiholeClient(**vars(cfg.pihole)).add_domain, domain, list_type=list_type, kind=kind
    )


async def pihole_remove_domain(cfg: Config, domain: str, list_type: str, kind: str) -> dict:
    return await asyncio.to_thread(
        PiholeClient(**vars(cfg.pihole)).remove_domain, domain, list_type=list_type, kind=kind
    )


async def pihole_local_dns(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_local_dns_records)


async def pihole_add_local_dns(cfg: Config, ip: str, hostname: str) -> dict:
    return await asyncio.to_thread(
        PiholeClient(**vars(cfg.pihole)).add_local_dns_record, ip, hostname
    )


async def pihole_remove_local_dns(cfg: Config, ip: str, hostname: str) -> dict:
    return await asyncio.to_thread(
        PiholeClient(**vars(cfg.pihole)).remove_local_dns_record, ip, hostname
    )


async def serve_static(request: Request) -> Response:
    path = request.path_params.get("path", "") or "index.html"
    if not _DIST.exists():
        return JSONResponse(
            {"error": "Dashboard not built. Run: cd dashboard && npm run build"},
            status_code=503,
        )
    file_path = (_DIST / path).resolve()
    dist_resolved = _DIST.resolve()
    if not file_path.is_relative_to(dist_resolved):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    index = dist_resolved / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"error": "Not found"}, status_code=404)
