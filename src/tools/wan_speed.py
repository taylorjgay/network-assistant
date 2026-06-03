from __future__ import annotations
import time

import speedtest

from src.tools.er605 import ER605Client
from src.tools.wan_health import _probe


class WANSpeedClient:
    def __init__(self, host: str, username: str, password: str):
        self._kwargs = {"host": host, "username": username, "password": password}

    def _er605(self) -> ER605Client:
        return ER605Client(**self._kwargs)

    def compare_wan_speed(self, quick: bool = False) -> dict:
        url = self._kwargs["host"]
        original = "auto"
        wan1_result = None
        wan2_result = None
        error = None
        restored = False
        switched = False
        try:
            policy = self._er605().get_wan_policy()
            if not policy["success"]:
                return {**policy, "quick": quick, "wan1": None, "wan2": None, "restored": False}
            original = policy.get("primary_wan", "auto")

            r = self._er605().set_wan_priority("WAN1")
            if not r["success"]:
                error = r
            else:
                switched = True
                time.sleep(2)
                wan1_result = self._measure(quick)

                r = self._er605().set_wan_priority("WAN2")
                if not r["success"]:
                    error = r
                else:
                    time.sleep(2)
                    server_id = wan1_result.get("_server_id") if wan1_result else None
                    wan2_result = self._measure(quick, server_id=server_id)
        except Exception as e:
            error = {"success": False, "error": str(e),
                     "suggestion": "Check ER605 connectivity", "attempted": url}
        finally:
            if switched:
                try:
                    r = self._er605().set_wan_priority(original)
                    restored = r.get("success", False)
                except Exception:
                    restored = False

        def _clean(r: dict | None) -> dict | None:
            return {k: v for k, v in r.items() if not k.startswith("_")} if r else None

        if error:
            return {**error, "quick": quick, "wan1": _clean(wan1_result),
                    "wan2": None, "restored": restored}

        return {
            "success": True,
            "quick": quick,
            "wan1": _clean(wan1_result),
            "wan2": _clean(wan2_result),
            "recommendation": _recommend(wan1_result, wan2_result, quick),
            "restored": restored,
        }

    def _measure(self, quick: bool, server_id: int | None = None) -> dict:
        if quick:
            raw = _probe()
            return {
                "latency_ms": raw["avg_latency_ms"],
                "packet_loss_pct": raw["packet_loss_pct"],
            }
        st = speedtest.Speedtest(secure=True)
        if server_id is not None:
            st.get_servers([server_id])
        st.get_best_server()
        dl_bps = st.download()
        ul_bps = st.upload()
        server = st.results.server
        return {
            "download_mbps": round(dl_bps / 1_000_000, 1),
            "upload_mbps": round(ul_bps / 1_000_000, 1),
            "latency_ms": st.results.ping,
            "server": server.get("name", ""),
            "_server_id": server.get("id"),
        }


def _recommend(wan1: dict | None, wan2: dict | None, quick: bool) -> str:
    if wan1 is None or wan2 is None:
        return "Incomplete data — could not compare"

    lat1 = wan1.get("latency_ms") if wan1.get("latency_ms") is not None else 999.0
    lat2 = wan2.get("latency_ms") if wan2.get("latency_ms") is not None else 999.0

    if quick:
        margin = abs(lat1 - lat2) / max(lat1, lat2)
        if margin < 0.10:
            return "Both WANs comparable — no strong recommendation"
        winner = "WAN1" if lat1 < lat2 else "WAN2"
        ratio = round(max(lat1, lat2) / min(lat1, lat2), 1)
        return f"{winner} recommended — {ratio}× lower latency"

    dl1 = wan1.get("download_mbps") if wan1.get("download_mbps") is not None else 0.0
    dl2 = wan2.get("download_mbps") if wan2.get("download_mbps") is not None else 0.0
    ul1 = wan1.get("upload_mbps") if wan1.get("upload_mbps") is not None else 0.0
    ul2 = wan2.get("upload_mbps") if wan2.get("upload_mbps") is not None else 0.0

    max_dl = max(dl1, dl2) if max(dl1, dl2) != 0.0 else 1.0
    max_ul = max(ul1, ul2) if max(ul1, ul2) != 0.0 else 1.0
    min_lat = min(lat1, lat2) if min(lat1, lat2) != 0.0 else 1.0

    score1 = (dl1 / max_dl) * 0.4 + (ul1 / max_ul) * 0.3 + (min_lat / max(lat1, 0.001)) * 0.3
    score2 = (dl2 / max_dl) * 0.4 + (ul2 / max_ul) * 0.3 + (min_lat / max(lat2, 0.001)) * 0.3

    margin = abs(score1 - score2) / (max(score1, score2) or 1.0)
    if margin < 0.10:
        return "Both WANs comparable — no strong recommendation"

    if score1 >= score2:
        winner = "WAN1"
        wdl, wul, wlat, ldl, lul, llat = dl1, ul1, lat1, dl2, ul2, lat2
    else:
        winner = "WAN2"
        wdl, wul, wlat, ldl, lul, llat = dl2, ul2, lat2, dl1, ul1, lat1

    reasons = []
    if ldl > 0 and wdl / ldl > 1.5:
        reasons.append(f"{round(wdl / ldl, 1)}× faster download")
    if lul > 0 and wul / lul > 1.5:
        reasons.append(f"{round(wul / lul, 1)}× faster upload")
    if wlat > 0 and llat / wlat > 1.5:
        reasons.append(f"{round(llat / wlat, 1)}× lower latency")

    suffix = ", ".join(reasons) if reasons else "better overall score"
    return f"{winner} recommended — {suffix}"
