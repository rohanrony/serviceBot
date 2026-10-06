import datetime as dt
from typing import Dict, Any, List, Optional
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.logger import get_logger

logger = get_logger("services.analytics")


def _get_time_filter_clause(timeframe: Optional[str], col_name: str = "created_at") -> str:
    """Builds a SQL interval filter clause based on timeframe."""
    tf = (timeframe or "7d").lower()
    if tf in ("24h", "1d"):
        return f" AND {col_name} >= NOW() - INTERVAL '24 hours'"
    elif tf == "7d":
        return f" AND {col_name} >= NOW() - INTERVAL '7 days'"
    elif tf == "30d":
        return f" AND {col_name} >= NOW() - INTERVAL '30 days'"
    elif tf in ("all", "all_time"):
        return ""
    # Default to 7 days
    return f" AND {col_name} >= NOW() - INTERVAL '7 days'"


def get_analytics_overview(timeframe: Optional[str] = "7d") -> Dict[str, Any]:
    """
    Returns executive summary KPIs for appointments, SLA compliance, and escalation resolution.
    """
    time_filter = _get_time_filter_clause(timeframe, "sr.created_at")

    query = f"""
    SELECT 
        COUNT(*) AS total_appointments,
        COUNT(CASE WHEN sr.confirmation_status = 'confirmed' THEN 1 END) AS total_confirmed,
        COUNT(CASE 
            WHEN sr.confirmation_status = 'confirmed' 
             AND sr.confirmation_cutoff_at IS NOT NULL 
             AND sr.confirmed_at IS NOT NULL 
             AND sr.confirmed_at <= sr.confirmation_cutoff_at 
            THEN 1 END) AS on_time_confirmed,
        COUNT(CASE 
            WHEN sr.confirmation_cutoff_at IS NOT NULL 
             AND ((sr.confirmed_at IS NOT NULL AND sr.confirmed_at > sr.confirmation_cutoff_at) 
                  OR (sr.confirmed_at IS NULL AND NOW() > sr.confirmation_cutoff_at AND sr.confirmation_status != 'cancelled'))
            THEN 1 END) AS breached_count,
        COUNT(CASE WHEN sr.escalation_status != 'none' THEN 1 END) AS total_escalated,
        COUNT(CASE WHEN sr.escalation_status = 'resolved' THEN 1 END) AS escalations_resolved,
        COUNT(CASE WHEN sr.escalation_status = 'reassigned' THEN 1 END) AS escalations_reassigned,
        COUNT(CASE WHEN sr.escalation_status = 'escalated' THEN 1 END) AS escalations_active_pending,
        AVG(CASE 
            WHEN sr.confirmed_at IS NOT NULL AND sr.created_at IS NOT NULL 
            THEN EXTRACT(EPOCH FROM (sr.confirmed_at - sr.created_at)) / 60.0 
            ELSE NULL END) AS avg_response_minutes
    FROM service_requests sr
    WHERE (sr.booking_type IS NULL OR sr.booking_type IN ('appointment', 'appointment_and_callback'))
      {time_filter};
    """

    recovery_query = f"""
    SELECT 
        AVG(EXTRACT(EPOCH FROM (res_log.created_at - esc_log.created_at)) / 60.0) AS avg_recovery_minutes
    FROM service_requests sr
    JOIN service_request_audit_log esc_log 
        ON esc_log.request_id = sr.id AND esc_log.to_status = 'escalated'
    JOIN service_request_audit_log res_log 
        ON res_log.request_id = sr.id 
       AND res_log.to_status IN ('resolved', 'reassigned')
       AND res_log.id > esc_log.id
    WHERE sr.escalation_status IN ('resolved', 'reassigned')
      {time_filter};
    """

    with get_db_connection() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(query)
            row = cur.fetchone() or {}

            cur.execute(recovery_query)
            rec_row = cur.fetchone() or {}

    total_appts = row.get("total_appointments") or 0
    total_confirmed = row.get("total_confirmed") or 0
    on_time_confirmed = row.get("on_time_confirmed") or 0
    breached_count = row.get("breached_count") or 0
    total_escalated = row.get("total_escalated") or 0
    escalations_resolved = row.get("escalations_resolved") or 0
    escalations_reassigned = row.get("escalations_reassigned") or 0
    escalations_active = row.get("escalations_active_pending") or 0

    evaluated_for_sla = on_time_confirmed + breached_count
    sla_on_time_pct = round((on_time_confirmed / evaluated_for_sla * 100.0), 1) if evaluated_for_sla > 0 else 100.0
    recovery_rate_pct = round(((escalations_resolved + escalations_reassigned) / total_escalated * 100.0), 1) if total_escalated > 0 else 100.0

    avg_response_min = round(float(row.get("avg_response_minutes") or 0), 1)
    avg_recovery_min = round(float(rec_row.get("avg_recovery_minutes") or 0), 1)

    return {
        "timeframe": timeframe or "7d",
        "total_appointments": total_appts,
        "total_confirmed": total_confirmed,
        "on_time_confirmed": on_time_confirmed,
        "breached_count": breached_count,
        "sla_on_time_pct": sla_on_time_pct,
        "total_escalated": total_escalated,
        "escalations_resolved": escalations_resolved,
        "escalations_reassigned": escalations_reassigned,
        "escalations_active": escalations_active,
        "recovery_rate_pct": recovery_rate_pct,
        "avg_response_minutes": avg_response_min,
        "avg_recovery_minutes": avg_recovery_min
    }


def get_sla_analytics(timeframe: Optional[str] = "7d") -> Dict[str, Any]:
    """
    Returns time-series daily trend and confirmation response latency distributions for SLA.
    """
    time_filter = _get_time_filter_clause(timeframe, "sr.created_at")

    trend_query = f"""
    SELECT 
        TO_CHAR(sr.created_at, 'YYYY-MM-DD') AS day,
        COUNT(*) AS total,
        COUNT(CASE 
            WHEN sr.confirmation_status = 'confirmed' 
             AND (sr.confirmation_cutoff_at IS NULL OR sr.confirmed_at <= sr.confirmation_cutoff_at)
            THEN 1 END) AS on_time,
        COUNT(CASE 
            WHEN sr.confirmation_cutoff_at IS NOT NULL 
             AND ((sr.confirmed_at IS NOT NULL AND sr.confirmed_at > sr.confirmation_cutoff_at)
                  OR (sr.confirmed_at IS NULL AND NOW() > sr.confirmation_cutoff_at AND sr.confirmation_status != 'cancelled'))
            THEN 1 END) AS breached
    FROM service_requests sr
    WHERE (sr.booking_type IS NULL OR sr.booking_type IN ('appointment', 'appointment_and_callback'))
      {time_filter}
    GROUP BY TO_CHAR(sr.created_at, 'YYYY-MM-DD')
    ORDER BY day ASC;
    """

    latency_query = f"""
    SELECT 
        COUNT(CASE WHEN diff_min < 15 THEN 1 END) AS under_15m,
        COUNT(CASE WHEN diff_min >= 15 AND diff_min < 60 THEN 1 END) AS between_15m_1h,
        COUNT(CASE WHEN diff_min >= 60 AND diff_min < 120 THEN 1 END) AS between_1h_2h,
        COUNT(CASE WHEN diff_min >= 120 AND diff_min < 240 THEN 1 END) AS between_2h_4h,
        COUNT(CASE WHEN diff_min >= 240 THEN 1 END) AS over_4h
    FROM (
        SELECT EXTRACT(EPOCH FROM (sr.confirmed_at - sr.created_at)) / 60.0 AS diff_min
        FROM service_requests sr
        WHERE sr.confirmation_status = 'confirmed' 
          AND sr.confirmed_at IS NOT NULL 
          AND sr.created_at IS NOT NULL
          {time_filter}
    ) sub;
    """

    with get_db_connection() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(trend_query)
            trend_rows = cur.fetchall() or []

            cur.execute(latency_query)
            latency_row = cur.fetchone() or {}

    timeline = [
        {
            "date": r["day"],
            "total": r["total"],
            "on_time": r["on_time"],
            "breached": r["breached"],
            "compliance_pct": round((r["on_time"] / (r["on_time"] + r["breached"]) * 100.0), 1) if (r["on_time"] + r["breached"]) > 0 else 100.0
        }
        for r in trend_rows
    ]

    return {
        "timeframe": timeframe or "7d",
        "timeline": timeline,
        "latency_distribution": {
            "under_15m": latency_row.get("under_15m") or 0,
            "15m_to_1h": latency_row.get("between_15m_1h") or 0,
            "1h_to_2h": latency_row.get("between_1h_2h") or 0,
            "2h_to_4h": latency_row.get("between_2h_4h") or 0,
            "over_4h": latency_row.get("over_4h") or 0
        }
    }


def get_escalation_analytics(timeframe: Optional[str] = "7d") -> Dict[str, Any]:
    """
    Returns breakdown of escalation reasons, recovery outcome funnels, and resolution latency.
    """
    time_filter = _get_time_filter_clause(timeframe, "sr.created_at")

    reasons_query = f"""
    SELECT 
        COALESCE(sr.escalation_reason, 'UNKNOWN') AS reason,
        COUNT(*) AS count
    FROM service_requests sr
    WHERE sr.escalation_status != 'none'
      {time_filter}
    GROUP BY COALESCE(sr.escalation_reason, 'UNKNOWN')
    ORDER BY count DESC;
    """

    outcomes_query = f"""
    SELECT 
        COUNT(CASE WHEN sr.escalation_status = 'resolved' THEN 1 END) AS recovered_by_agent,
        COUNT(CASE WHEN sr.escalation_status = 'reassigned' THEN 1 END) AS supervisor_reassigned,
        COUNT(CASE WHEN sr.escalation_status = 'escalated' THEN 1 END) AS active_unresolved,
        COUNT(CASE WHEN sr.status IN ('cancelled', 'cancelled_by_customer') THEN 1 END) AS cancelled
    FROM service_requests sr
    WHERE sr.escalation_status != 'none'
      {time_filter};
    """

    with get_db_connection() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(reasons_query)
            reason_rows = cur.fetchall() or []

            cur.execute(outcomes_query)
            outcome_row = cur.fetchone() or {}

    reasons_map = {r["reason"]: r["count"] for r in reason_rows}

    return {
        "timeframe": timeframe or "7d",
        "reasons": reasons_map,
        "outcomes": {
            "recovered_by_agent": outcome_row.get("recovered_by_agent") or 0,
            "supervisor_reassigned": outcome_row.get("supervisor_reassigned") or 0,
            "active_unresolved": outcome_row.get("active_unresolved") or 0,
            "cancelled": outcome_row.get("cancelled") or 0
        }
    }


def get_technician_scorecard(timeframe: Optional[str] = "7d") -> List[Dict[str, Any]]:
    """
    Returns performance scorecard per staff agent/technician.
    """
    time_filter = _get_time_filter_clause(timeframe, "sr.created_at")

    query = f"""
    SELECT 
        sa.id AS agent_id,
        sa.name AS agent_name,
        sa.email,
        sa.role,
        COUNT(sr.id) AS total_assigned,
        COUNT(CASE WHEN sr.confirmation_status = 'confirmed' THEN 1 END) AS confirmed_count,
        COUNT(CASE 
            WHEN sr.confirmation_status = 'confirmed' 
             AND (sr.confirmation_cutoff_at IS NULL OR sr.confirmed_at <= sr.confirmation_cutoff_at)
            THEN 1 END) AS on_time_count,
        COUNT(CASE WHEN sr.escalation_status != 'none' THEN 1 END) AS escalated_count,
        COUNT(CASE WHEN sr.escalation_status = 'reassigned' THEN 1 END) AS reassigned_count,
        AVG(CASE 
            WHEN sr.confirmed_at IS NOT NULL AND sr.created_at IS NOT NULL 
            THEN EXTRACT(EPOCH FROM (sr.confirmed_at - sr.created_at)) / 60.0 
            ELSE NULL END) AS avg_response_minutes
    FROM staff_agents sa
    LEFT JOIN service_requests sr 
        ON sr.staff_agent_id = sa.id 
       AND (sr.booking_type IS NULL OR sr.booking_type IN ('appointment', 'appointment_and_callback'))
       {time_filter}
    GROUP BY sa.id, sa.name, sa.email, sa.role
    ORDER BY total_assigned DESC, sa.name ASC;
    """

    with get_db_connection() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(query)
            rows = cur.fetchall() or []

    scorecard = []
    for r in rows:
        assigned = r["total_assigned"] or 0
        confirmed = r["confirmed_count"] or 0
        on_time = r["on_time_count"] or 0
        escalated = r["escalated_count"] or 0
        reassigned = r["reassigned_count"] or 0
        avg_resp = round(float(r["avg_response_minutes"] or 0), 1)

        on_time_pct = round((on_time / confirmed * 100.0), 1) if confirmed > 0 else (100.0 if assigned == 0 else 0.0)

        scorecard.append({
            "agent_id": r["agent_id"],
            "agent_name": r["agent_name"],
            "email": r["email"] or "N/A",
            "role": r["role"] or "Technician",
            "total_assigned": assigned,
            "confirmed_count": confirmed,
            "on_time_count": on_time,
            "on_time_pct": on_time_pct,
            "escalated_count": escalated,
            "reassigned_count": reassigned,
            "avg_response_minutes": avg_resp
        })

    return scorecard
