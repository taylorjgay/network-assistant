import subprocess
from unittest.mock import patch, MagicMock
import pytest
from src.tools.diagnostics import ping_host, traceroute_host, test_dns_resolution as _dns_resolve


def test_ping_host_success():
    mock_output = (
        "PING 8.8.8.8 (8.8.8.8): 56 data bytes\n"
        "64 bytes from 8.8.8.8: icmp_seq=0 ttl=118 time=12.3 ms\n"
        "--- 8.8.8.8 ping statistics ---\n"
        "4 packets transmitted, 4 packets received, 0.0% packet loss\n"
        "round-trip min/avg/max/stddev = 11.2/12.3/13.4/0.8 ms\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
        result = ping_host("8.8.8.8", count=4)
    assert result["success"] is True
    assert result["host"] == "8.8.8.8"
    assert result["packet_loss_pct"] == 0.0
    assert result["avg_ms"] == 12.3


def test_ping_host_unreachable():
    mock_output = (
        "--- 10.0.0.99 ping statistics ---\n"
        "4 packets transmitted, 0 packets received, 100.0% packet loss\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=2, stdout=mock_output, stderr="")
        result = ping_host("10.0.0.99", count=4)
    assert result["success"] is True  # tool succeeded, host is unreachable
    assert result["packet_loss_pct"] == 100.0


def test_ping_host_timeout():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ping", timeout=10)
        result = ping_host("10.0.0.99", count=4)
    assert result["success"] is False
    assert "timed out" in result["error"].lower()


def test_traceroute_host_success():
    mock_output = (
        "traceroute to 8.8.8.8, 30 hops max\n"
        " 1  192.168.0.1  1.234 ms\n"
        " 2  10.0.0.1  5.678 ms\n"
        " 3  8.8.8.8  12.345 ms\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
        result = traceroute_host("8.8.8.8")
    assert result["success"] is True
    assert result["host"] == "8.8.8.8"
    assert len(result["hops"]) == 3
    assert result["hops"][0]["ip"] == "192.168.0.1"


def test_test_dns_resolution_success():
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(2, 1, 6, "", ("142.250.80.46", 0))]
        result = _dns_resolve("google.com")
    assert result["success"] is True
    assert "142.250.80.46" in result["addresses"]
    assert result["hostname"] == "google.com"


def test_test_dns_resolution_failure():
    import socket
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.side_effect = socket.gaierror("Name or service not known")
        result = _dns_resolve("doesnotexist.invalid")
    assert result["success"] is False
    assert "suggestion" in result
