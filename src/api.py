import asyncio
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from src.config import Config
from src.tools.deco import DecoClient
from src.tools.devices import DeviceInventory
from src.tools.er605 import ER605Client, ER605Evicted, ER605Session, parse_router_info, parse_wan_status
from src.tools.pihole import PiholeClient
from src.tools.upnp import get_upnp_portmaps, get_upnp_status
from src.tools.diagnostics import (
    ping_host as _ping_host,
    traceroute_host as _traceroute_host,
    run_speedtest as _run_speedtest,
    test_dns_resolution as _test_dns_resolution,
)
from src.tools.wan_health import WANHealthClient, health_from_wan_status
from src.tools.wan_speed import WANSpeedClient

_LABELS_PATH = Path(__file__).parent.parent / "devices.json"
_DIST = Path(__file__).parent.parent / "dashboard" / "dist"

_snapshot_cache: dict | None = None
_snapshot_ts: float = 0.0
_snapshot_lock = asyncio.Lock()
# A request finding the cache older than this starts a background refresh.
_REFRESH_AFTER = 20.0
# Older than this, a served snapshot is flagged `stale` and the page shows it as a dimmed
# placeholder. Above the normal refresh cycle (warmer every 25s plus a ~10s snapshot), so
# routine polling never trips it.
_STALE_AFTER = 90.0
_refresh_task: asyncio.Task | None = None

# Which Deco each client is on costs ~25s of Deco time (one 5-7s query per node), so the
# Network page never fetches it. While the dashboard is open, requests start a background
# refresh at most this often, and the device inventory shows the cached result.
_DECO_CLIENTS_EVERY = 300.0
_deco_clients_started: float = float("-inf")
_deco_clients_task: asyncio.Task | None = None

# The warmer stops once the dashboard has made no snapshot request for this long.
# React Query skips refetches in hidden tabs, so a quiet period means nobody is looking.
_WARMER_IDLE_STOP = 120.0
_last_snapshot_request: float = 0.0

# The ER605 allows one admin session, so polling holds a single reused login. When someone
# else logs in (normally the web UI), stop polling the router for a while rather than
# kicking them out on the next cycle. Calls run under _snapshot_lock, never concurrently.
_ER605_PAUSE = 15 * 60.0
_er605_session: ER605Session | None = None
_er605_paused_until: float = 0.0
_er605_last: tuple[dict, dict] | None = None


def _er605_paused(now: float) -> tuple[dict, dict]:
    note = {"paused": True, "paused_seconds_left": round(_er605_paused_until - now)}
    if _er605_last is not None:
        wan, router = _er605_last
        return {**wan, **note}, {**router, **note}
    err = {"success": False, "error": "Paused: someone is logged in to the router web UI", **note}
    return err, dict(err)


def _poll_er605(cfg: Config) -> tuple[dict, dict]:
    """WAN health and router info over the shared ER605 session. Blocking; run in a thread."""
    global _er605_session, _er605_paused_until, _er605_last
    now = time.monotonic()
    if now < _er605_paused_until:
        return _er605_paused(now)
    if _er605_session is None:
        _er605_session = ER605Session(**vars(cfg.er605))
    url = f"https://{cfg.er605.host}"
    try:
        status = _er605_session.get("interface", "status2")
        fw = _er605_session.get("firmware", "upgrade")
        sys_usage = _er605_session.get("sys_status", "all_usage")
        uptime = _er605_session.uptime()
    except ER605Evicted:
        _er605_paused_until = now + _ER605_PAUSE
        return _er605_paused(now)
    except Exception as e:
        _er605_session.close()
        err = {"success": False, "error": str(e), "suggestion": "Check ER605 connectivity at the configured host", "attempted": url}
        return err, dict(err)

    wan_status = parse_wan_status(status, url)
    wan = health_from_wan_status(wan_status) if wan_status["success"] else wan_status
    router = parse_router_info(fw, sys_usage, uptime, url)
    if wan.get("success") and router.get("success"):
        _er605_last = (wan, router)
    return wan, router


async def _do_snapshot(cfg: Config) -> dict:
    # Pi-hole and Deco hit different devices so they run in parallel with ER605.
    async def _er605_sequential():
        return await asyncio.to_thread(_poll_er605, cfg)

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


def _refresh_deco_clients(cfg: Config) -> None:
    """Start a background Deco client-list refresh if the last one is old enough and done."""
    global _deco_clients_started, _deco_clients_task
    now = time.monotonic()
    if now - _deco_clients_started < _DECO_CLIENTS_EVERY:
        return
    if _deco_clients_task is not None and not _deco_clients_task.done():
        return
    _deco_clients_started = now
    _deco_clients_task = asyncio.create_task(
        asyncio.to_thread(DecoClient(**vars(cfg.deco)).get_connected_clients))


def _with_age(snap: dict, ts: float, now: float) -> dict:
    age = now - ts
    return {**snap, "age_seconds": round(age), "stale": age > _STALE_AFTER}


async def snapshot(cfg: Config) -> dict:
    """Serve the cached snapshot at once, whatever its age, and refresh it in the background.

    Polling stops when the dashboard closes, so the cache can be days old when the page is
    next opened. Serving it anyway lets the page lay out instantly; `stale` tells the page
    to treat it as a placeholder and re-ask until fresh data lands (one Deco login, ~10s).
    Only the very first request after a restart waits for a full snapshot.
    """
    global _snapshot_cache, _snapshot_ts, _last_snapshot_request, _refresh_task
    now = time.monotonic()
    _last_snapshot_request = now
    if _snapshot_cache is not None:
        if now - _snapshot_ts > _REFRESH_AFTER and (_refresh_task is None or _refresh_task.done()):
            _refresh_task = asyncio.create_task(_background_refresh(cfg))
        elif now - _snapshot_ts <= _STALE_AFTER:
            # Only once the page has fresh data: the client refresh holds the Deco for ~25s,
            # and the snapshot's own Deco call would otherwise queue behind it.
            _refresh_deco_clients(cfg)
        return _with_age(_snapshot_cache, _snapshot_ts, now)
    async with _snapshot_lock:
        if _snapshot_cache is None:
            _snapshot_cache = await _do_snapshot(cfg)
            _snapshot_ts = time.monotonic()
        return _with_age(_snapshot_cache, _snapshot_ts, time.monotonic())


async def _background_refresh(cfg: Config) -> None:
    global _snapshot_cache, _snapshot_ts
    if _snapshot_lock.locked():
        return
    async with _snapshot_lock:
        try:
            result = await _do_snapshot(cfg)
            _snapshot_cache = result
            _snapshot_ts = time.monotonic()
        except Exception:
            pass


async def warm_snapshot_loop(cfg: Config) -> None:
    """Refreshes the snapshot cache every 25s while the dashboard is being viewed.
    Started on a snapshot request; exits after _WARMER_IDLE_STOP without one, and the
    next snapshot request starts it again."""
    global _snapshot_cache, _snapshot_ts
    while True:
        await asyncio.sleep(25)
        if time.monotonic() - _last_snapshot_request > _WARMER_IDLE_STOP:
            return
        async with _snapshot_lock:
            try:
                result = await _do_snapshot(cfg)
                _snapshot_cache = result
                _snapshot_ts = time.monotonic()
            except Exception:
                pass


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
    _refresh_deco_clients(cfg)
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
