import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.services.analytics import (
    get_analytics_overview,
    get_sla_analytics,
    get_escalation_analytics,
    get_technician_scorecard
)

client = TestClient(app)

MOCK_OVERVIEW_ROW = {
    "total_appointments": 10,
    "total_confirmed": 8,
    "on_time_confirmed": 7,
    "breached_count": 2,
    "total_escalated": 3,
    "escalations_resolved": 2,
    "escalations_reassigned": 1,
    "escalations_active_pending": 0,
    "avg_response_minutes": 24.5
}

MOCK_RECOVERY_ROW = {
    "avg_recovery_minutes": 15.2
}

MOCK_TREND_ROWS = [
    {"day": "2026-10-01", "total": 5, "on_time": 4, "breached": 1},
    {"day": "2026-10-02", "total": 5, "on_time": 3, "breached": 1}
]

MOCK_LATENCY_ROW = {
    "under_15m": 4,
    "between_15m_1h": 3,
    "between_1h_2h": 1,
    "between_2h_4h": 0,
    "over_4h": 0
}

MOCK_REASONS_ROWS = [
    {"reason": "TIMEOUT_NO_RESPONSE", "count": 2},
    {"reason": "AGENT_DECLINED", "count": 1}
]

MOCK_OUTCOMES_ROW = {
    "recovered_by_agent": 2,
    "supervisor_reassigned": 1,
    "active_unresolved": 0,
    "cancelled": 0
}

MOCK_SCORECARD_ROWS = [
    {
        "agent_id": 1,
        "agent_name": "Marcus Vance",
        "email": "marcus@shop.com",
        "role": "Lead Tech",
        "total_assigned": 6,
        "confirmed_count": 5,
        "on_time_count": 5,
        "escalated_count": 1,
        "reassigned_count": 0,
        "avg_response_minutes": 12.0
    },
    {
        "agent_id": 2,
        "agent_name": "Elena Rostova",
        "email": "elena@shop.com",
        "role": "Technician",
        "total_assigned": 4,
        "confirmed_count": 3,
        "on_time_count": 2,
        "escalated_count": 2,
        "reassigned_count": 1,
        "avg_response_minutes": 38.0
    }
]


def test_get_analytics_overview():
    with patch("serviceBot.services.analytics.get_db_connection") as mock_conn:
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [MOCK_OVERVIEW_ROW, MOCK_RECOVERY_ROW]
        mock_conn.return_value.__enter__.return_value = MagicMock()
        with patch("serviceBot.services.analytics.dict_cursor") as mock_dict_cur:
            mock_dict_cur.return_value.__enter__.return_value = mock_cur
            res = get_analytics_overview("7d")

            assert res["total_appointments"] == 10
            assert res["total_confirmed"] == 8
            assert res["on_time_confirmed"] == 7
            assert res["breached_count"] == 2
            # Evaluated for SLA = 7 + 2 = 9. 7/9 * 100 = 77.8%
            assert res["sla_on_time_pct"] == 77.8
            assert res["total_escalated"] == 3
            assert res["recovery_rate_pct"] == 100.0
            assert res["avg_response_minutes"] == 24.5
            assert res["avg_recovery_minutes"] == 15.2


def test_get_sla_analytics():
    with patch("serviceBot.services.analytics.get_db_connection") as mock_conn:
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = MOCK_TREND_ROWS
        mock_cur.fetchone.return_value = MOCK_LATENCY_ROW
        mock_conn.return_value.__enter__.return_value = MagicMock()
        with patch("serviceBot.services.analytics.dict_cursor") as mock_dict_cur:
            mock_dict_cur.return_value.__enter__.return_value = mock_cur
            res = get_sla_analytics("7d")

            assert len(res["timeline"]) == 2
            assert res["timeline"][0]["date"] == "2026-10-01"
            assert res["timeline"][0]["compliance_pct"] == 80.0
            assert res["latency_distribution"]["under_15m"] == 4
            assert res["latency_distribution"]["15m_to_1h"] == 3


def test_get_escalation_analytics():
    with patch("serviceBot.services.analytics.get_db_connection") as mock_conn:
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = MOCK_REASONS_ROWS
        mock_cur.fetchone.return_value = MOCK_OUTCOMES_ROW
        mock_conn.return_value.__enter__.return_value = MagicMock()
        with patch("serviceBot.services.analytics.dict_cursor") as mock_dict_cur:
            mock_dict_cur.return_value.__enter__.return_value = mock_cur
            res = get_escalation_analytics("7d")

            assert res["reasons"]["TIMEOUT_NO_RESPONSE"] == 2
            assert res["reasons"]["AGENT_DECLINED"] == 1
            assert res["outcomes"]["recovered_by_agent"] == 2
            assert res["outcomes"]["supervisor_reassigned"] == 1


def test_get_technician_scorecard():
    with patch("serviceBot.services.analytics.get_db_connection") as mock_conn:
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = MOCK_SCORECARD_ROWS
        mock_conn.return_value.__enter__.return_value = MagicMock()
        with patch("serviceBot.services.analytics.dict_cursor") as mock_dict_cur:
            mock_dict_cur.return_value.__enter__.return_value = mock_cur
            scorecard = get_technician_scorecard("7d")

            assert len(scorecard) == 2
            assert scorecard[0]["agent_name"] == "Marcus Vance"
            assert scorecard[0]["on_time_pct"] == 100.0
            assert scorecard[1]["agent_name"] == "Elena Rostova"
            assert scorecard[1]["on_time_pct"] == 66.7


def test_portal_analytics_api_endpoints():
    with patch("serviceBot.services.analytics.get_analytics_overview", return_value={"total_appointments": 5}):
        res1 = client.get("/api/v1/portal/analytics/overview?timeframe=24h")
        assert res1.status_code == 200
        assert res1.json()["total_appointments"] == 5

    with patch("serviceBot.services.analytics.get_sla_analytics", return_value={"timeline": []}):
        res2 = client.get("/api/v1/portal/analytics/sla?timeframe=7d")
        assert res2.status_code == 200
        assert "timeline" in res2.json()

    with patch("serviceBot.services.analytics.get_escalation_analytics", return_value={"reasons": {}}):
        res3 = client.get("/api/v1/portal/analytics/escalations?timeframe=30d")
        assert res3.status_code == 200
        assert "reasons" in res3.json()

    with patch("serviceBot.services.analytics.get_technician_scorecard", return_value=[]):
        res4 = client.get("/api/v1/portal/analytics/technicians?timeframe=all")
        assert res4.status_code == 200
        assert isinstance(res4.json(), list)
