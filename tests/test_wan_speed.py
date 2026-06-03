import pytest
from unittest.mock import patch, MagicMock, call
from src.tools.wan_speed import WANSpeedClient
from src.tools.er605 import ER605Client


@pytest.fixture
def client():
    return WANSpeedClient(host="192.168.0.1", username="admin", password="secret")


POLICY_OK = {"success": True, "primary_wan": "WAN1"}
SET_OK = {"success": True}
SET_FAIL = {"success": False, "error": "set failed"}

PROBE_WAN1 = {"targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"], "avg_latency_ms": 12.0, "packet_loss_pct": 0.0}
PROBE_WAN2 = {"targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"], "avg_latency_ms": 28.0, "packet_loss_pct": 0.0}
PROBE_CLOSE = {"targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"], "avg_latency_ms": 13.0, "packet_loss_pct": 0.0}


def _mock_er605(policy=POLICY_OK, set_result=SET_OK):
    m = MagicMock(spec=ER605Client)
    m.get_wan_policy.return_value = policy
    m.set_wan_priority.return_value = set_result
    return m


class TestQuickMode:
    def test_wan1_wins(self, client):
        er = _mock_er605()
        with patch.object(client, "_er605", return_value=er):
            with patch("src.tools.wan_speed._probe", side_effect=[PROBE_WAN1, PROBE_WAN2]):
                result = client.compare_wan_speed(quick=True)

        assert result["success"] is True
        assert result["quick"] is True
        assert result["wan1"]["latency_ms"] == 12.0
        assert result["wan1"]["packet_loss_pct"] == 0.0
        assert result["wan2"]["latency_ms"] == 28.0
        assert "WAN1" in result["recommendation"]
        assert result["restored"] is True

    def test_wan2_wins(self, client):
        er = _mock_er605()
        with patch.object(client, "_er605", return_value=er):
            with patch("src.tools.wan_speed._probe", side_effect=[PROBE_WAN2, PROBE_WAN1]):
                result = client.compare_wan_speed(quick=True)

        assert result["success"] is True
        assert "WAN2" in result["recommendation"]

    def test_tie_within_10pct(self, client):
        # 12 vs 13 ms — margin = 1/13 = 7.7% < 10%
        er = _mock_er605()
        with patch.object(client, "_er605", return_value=er):
            with patch("src.tools.wan_speed._probe", side_effect=[PROBE_WAN1, PROBE_CLOSE]):
                result = client.compare_wan_speed(quick=True)

        assert "comparable" in result["recommendation"].lower()

    def test_wan1_switch_fails_aborts(self, client):
        er = _mock_er605(set_result=SET_FAIL)
        with patch.object(client, "_er605", return_value=er):
            result = client.compare_wan_speed(quick=True)

        assert result["success"] is False
        assert "set failed" in result["error"]

    def test_wan2_switch_fails_partial_results(self, client):
        er = MagicMock(spec=ER605Client)
        er.get_wan_policy.return_value = POLICY_OK
        # WAN1 switch succeeds, WAN2 switch fails
        er.set_wan_priority.side_effect = [SET_OK, SET_FAIL, SET_OK]
        with patch.object(client, "_er605", return_value=er):
            with patch("src.tools.wan_speed._probe", return_value=PROBE_WAN1):
                result = client.compare_wan_speed(quick=True)

        assert result["success"] is False
        assert result["wan1"] is not None
        assert result["wan2"] is None
        assert result["restored"] is True

    def test_restore_always_runs(self, client):
        er = MagicMock(spec=ER605Client)
        er.get_wan_policy.return_value = POLICY_OK
        er.set_wan_priority.return_value = SET_OK
        with patch.object(client, "_er605", return_value=er):
            with patch("src.tools.wan_speed._probe", side_effect=Exception("probe exploded")):
                result = client.compare_wan_speed(quick=True)

        # set_wan_priority should have been called for WAN1 + restore
        assert er.set_wan_priority.call_count >= 2
        assert result["restored"] is True

    def test_restore_fails_reported(self, client):
        er = MagicMock(spec=ER605Client)
        er.get_wan_policy.return_value = POLICY_OK
        # All set calls fail after first
        er.set_wan_priority.side_effect = [SET_OK, SET_OK, SET_FAIL]
        with patch.object(client, "_er605", return_value=er):
            with patch("src.tools.wan_speed._probe", side_effect=[PROBE_WAN1, PROBE_WAN2]):
                result = client.compare_wan_speed(quick=True)

        assert result["restored"] is False

    def test_policy_failure_returns_uniform_envelope(self, client):
        er = _mock_er605(policy={"success": False, "error": "auth failed"})
        with patch.object(client, "_er605", return_value=er):
            result = client.compare_wan_speed(quick=True)

        assert result["success"] is False
        assert "auth failed" in result["error"]
        assert result["quick"] is True
        assert result["wan1"] is None
        assert result["wan2"] is None
        assert result["restored"] is False

    def test_clean_strips_underscore_keys(self, client):
        er = _mock_er605()
        with patch.object(client, "_er605", return_value=er):
            with patch("src.tools.wan_speed._probe", side_effect=[PROBE_WAN1, PROBE_WAN2]):
                result = client.compare_wan_speed(quick=True)

        # Quick mode never produces _-prefixed keys, but _clean must not pass them through
        assert all(not k.startswith("_") for k in result["wan1"].keys())
        assert all(not k.startswith("_") for k in result["wan2"].keys())
