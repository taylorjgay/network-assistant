import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from src.tools.er605 import ER605Client


_PING_TARGETS = ["1.1.1.1", "8.8.8.8", "8.8.4.4"]
_DEGRADED_LOSS_PCT = 5.0
_DEGRADED_LATENCY_MS = 150.0


def _ping_target(target: str) -> dict:
    try:
        result = subprocess.run(
            ["ping", "-c", "5", "-i", "0.2", target],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout
        loss_match = re.search(r"([\d.]+)% packet loss", output)
        packet_loss = float(loss_match.group(1)) if loss_match else 100.0
        avg_ms = None
        rtt_match = re.search(r"min/avg/max/[^\s]+ = [\d.]+/([\d.]+)/", output)
        if rtt_match:
            avg_ms = float(rtt_match.group(1))
        return {"target": target, "avg_latency_ms": avg_ms, "packet_loss_pct": packet_loss}
    except Exception:
        return {"target": target, "avg_latency_ms": None, "packet_loss_pct": 100.0}


def _probe() -> dict:
    results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_ping_target, t) for t in _PING_TARGETS]
        for f in futures:
            results.append(f.result())
    valid = [r["avg_latency_ms"] for r in results if r["avg_latency_ms"] is not None]
    avg_latency = round(sum(valid) / len(valid), 1) if valid else None
    avg_loss = round(sum(r["packet_loss_pct"] for r in results) / len(results), 1)
    return {
        "targets": list(_PING_TARGETS),
        "avg_latency_ms": avg_latency,
        "packet_loss_pct": avg_loss,
    }


def _is_degraded(probe: dict) -> bool:
    return (probe.get("packet_loss_pct", 0.0) > _DEGRADED_LOSS_PCT or
            (probe.get("avg_latency_ms") or 0.0) > _DEGRADED_LATENCY_MS)


class WANHealthClient:
    def __init__(self, host: str, username: str, password: str):
        self._kwargs = {"host": host, "username": username, "password": password}

    def _er605(self) -> ER605Client:
        return ER605Client(**self._kwargs)

    def get_wan_health(self) -> dict:
        url = self._kwargs["host"]
        try:
            wan_status = self._er605().get_wan_status()
            if not wan_status["success"]:
                return wan_status

            ifaces = {i["name"]: i for i in wan_status.get("interfaces", [])}

            def _parse(name: str) -> dict | None:
                i = ifaces.get(name)
                if i is None:
                    return None
                return {
                    "link": "up" if i.get("up") else "down",
                    "ip": i.get("ip") or None,
                    "gateway": i.get("gateway") or None,
                }

            wan1 = _parse("WAN1")
            wan2 = _parse("WAN2")

            active_wan = None
            if wan1 and wan1["link"] == "up" and wan1["ip"]:
                active_wan = "WAN1"
            elif wan2 and wan2["link"] == "up" and wan2["ip"]:
                active_wan = "WAN2"

            probe = _probe()
            return {
                "success": True,
                "active_wan": active_wan,
                "wan1": wan1,
                "wan2": wan2,
                "probe": probe,
                "degraded": _is_degraded(probe),
            }
        except Exception as e:
            return {"success": False, "error": str(e), "suggestion": "Check ER605 connectivity at the configured host", "attempted": url}

    def compare_wan_health(self) -> dict:
        url = self._kwargs["host"]
        original = "auto"
        wan1_probe = None
        wan2_probe = None
        error = None
        restored = False
        switched = False  # track if we actually changed WAN priority
        try:
            policy = self._er605().get_wan_policy()
            if not policy["success"]:
                return policy
            original = policy.get("primary_wan", "auto")

            r = self._er605().set_wan_priority("WAN1")
            if not r["success"]:
                error = r
            else:
                switched = True
                time.sleep(2)
                raw = _probe()
                wan1_probe = {
                    "avg_latency_ms": raw["avg_latency_ms"],
                    "packet_loss_pct": raw["packet_loss_pct"],
                    "degraded": _is_degraded(raw),
                }
                r = self._er605().set_wan_priority("WAN2")
                if not r["success"]:
                    error = r
                else:
                    time.sleep(2)
                    raw = _probe()
                    wan2_probe = {
                        "avg_latency_ms": raw["avg_latency_ms"],
                        "packet_loss_pct": raw["packet_loss_pct"],
                        "degraded": _is_degraded(raw),
                    }
        except Exception as e:
            error = {"success": False, "error": str(e), "suggestion": "Check ER605 connectivity at the configured host", "attempted": url}
        finally:
            if switched:
                try:
                    r = self._er605().set_wan_priority(original)
                    restored = r.get("success", False)
                except Exception:
                    restored = False

        if error:
            return {**error, "restored": restored}

        w1_ok = wan1_probe is not None and not wan1_probe["degraded"]
        w2_ok = wan2_probe is not None and not wan2_probe["degraded"]
        if w1_ok and w2_ok:
            l1 = wan1_probe["avg_latency_ms"] or 999
            l2 = wan2_probe["avg_latency_ms"] or 999
            rec = ("Both WANs healthy — WAN1 has lower latency" if l1 <= l2
                   else "Both WANs healthy — WAN2 has lower latency")
        elif w1_ok:
            rec = "WAN1 is healthier — stay on current configuration"
        elif w2_ok:
            rec = "WAN2 is healthier — consider switching primary WAN"
        else:
            rec = "Both WANs degraded — check upstream connections"

        return {
            "success": True,
            "original_policy": original,
            "wan1_probe": wan1_probe,
            "wan2_probe": wan2_probe,
            "recommendation": rec,
            "restored": restored,
        }
