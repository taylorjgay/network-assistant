import re
import socket
import subprocess
import time


def ping_host(host: str, count: int = 4) -> dict:
    """Ping a host, return latency and packet loss."""
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), host],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout
        loss_match = re.search(r"([\d.]+)% packet loss", output)
        packet_loss = float(loss_match.group(1)) if loss_match else 100.0
        avg_ms = None
        rtt_match = re.search(r"min/avg/max/[^\s]+ = [\d.]+/([\d.]+)/", output)
        if rtt_match:
            avg_ms = float(rtt_match.group(1))
        return {
            "success": True,
            "host": host,
            "packets_sent": count,
            "packet_loss_pct": packet_loss,
            "avg_ms": avg_ms,
            "reachable": packet_loss < 100.0,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "host": host, "error": "ping timed out after 15s",
                "suggestion": "Host may be unreachable or firewall is blocking ICMP"}
    except Exception as e:
        return {"success": False, "host": host, "error": str(e), "suggestion": "Check that 'ping' is available on PATH"}


def traceroute_host(host: str) -> dict:
    """Traceroute to a host, returning each hop."""
    try:
        result = subprocess.run(
            ["traceroute", "-n", host],
            capture_output=True, text=True, timeout=60
        )
        hops = []
        for line in result.stdout.splitlines():
            m = re.match(r"\s*(\d+)\s+([\d.]+|\*)\s+([\d.]+)\s+ms", line)
            if m:
                hops.append({"hop": int(m.group(1)), "ip": m.group(2), "ms": float(m.group(3))})
            else:
                timeout_m = re.match(r"\s*(\d+)\s+(\*\s*)+$", line)
                if timeout_m:
                    hops.append({"hop": int(timeout_m.group(1)), "ip": None, "ms": None, "timeout": True})
        return {"success": True, "host": host, "hops": hops, "raw": result.stdout}
    except subprocess.TimeoutExpired:
        return {"success": False, "host": host, "error": "traceroute timed out after 60s",
                "suggestion": "Host may be many hops away or a firewall is blocking ICMP responses"}
    except Exception as e:
        return {"success": False, "host": host, "error": str(e), "suggestion": "Check that 'traceroute' is available on PATH"}


def test_dns_resolution(hostname: str, dns_server: str = None) -> dict:
    """Resolve a hostname and return the addresses."""
    start = time.monotonic()
    try:
        if dns_server:
            # Use dig for custom DNS server
            result = subprocess.run(
                ["dig", f"@{dns_server}", hostname, "+short"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                elapsed_ms = (time.monotonic() - start) * 1000
                return {"success": False, "hostname": hostname, "dns_server": dns_server,
                        "error": result.stderr.strip() or f"dig exited with code {result.returncode}",
                        "suggestion": f"Check that '{dns_server}' is reachable and is a valid DNS server"}
            addresses = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            elapsed_ms = (time.monotonic() - start) * 1000
            return {"success": True, "hostname": hostname, "dns_server": dns_server,
                    "addresses": addresses, "elapsed_ms": round(elapsed_ms, 1)}
        else:
            infos = socket.getaddrinfo(hostname, None)
            addresses = list({info[4][0] for info in infos})
            elapsed_ms = (time.monotonic() - start) * 1000
            return {"success": True, "hostname": hostname, "dns_server": "system default",
                    "addresses": addresses, "elapsed_ms": round(elapsed_ms, 1)}
    except socket.gaierror as e:
        return {"success": False, "hostname": hostname, "error": str(e),
                "suggestion": "DNS resolution failed — Pi-hole may be blocking this domain or DNS is misconfigured"}
    except Exception as e:
        return {"success": False, "hostname": hostname, "error": str(e),
                "suggestion": "Check that 'dig' is available on PATH if using a custom DNS server"}


def run_speedtest() -> dict:
    """Run an internet speed test."""
    try:
        import ssl, certifi
        ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    try:
        import speedtest
        st = speedtest.Speedtest(secure=True)
        st.get_best_server()
        download_bps = st.download()
        upload_bps = st.upload()
        results = st.results.dict()
        return {
            "success": True,
            "download_mbps": round(download_bps / 1_000_000, 1),
            "upload_mbps": round(upload_bps / 1_000_000, 1),
            "ping_ms": results.get("ping"),
            "server": results.get("server", {}).get("name"),
            "server_location": f"{results.get('server', {}).get('city')}, {results.get('server', {}).get('country')}",
        }
    except Exception as e:
        return {"success": False, "error": str(e),
                "suggestion": "Check internet connectivity; speedtest-cli must be installed"}
