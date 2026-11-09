"""How good are the warnings? Lead time, precision, recall and false alarms per week.

Ground truth is the incident log: a ranger (or the demo scenario) records when an animal
actually reached a village. An alert counts as correct if an incident in the same village
follows it within the evaluation window.
"""

from __future__ import annotations

from datetime import datetime
from statistics import median

from . import config, db
from .config import TIME_FORMAT


def _t(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def evaluate(window_min: int = config.EVAL_WINDOW_MIN) -> dict:
    alerts = sorted(
        (
            n for n in db.list_notifications(limit=5000)
            if n.get("channel", "sms") == "sms" and n["status"] in ("sent", "dry_run")
        ),
        key=lambda n: n["timestamp"],
    )
    incidents = db.list_incidents()
    window_s = window_min * 60

    rows = []
    for alert in alerts:
        at = _t(alert["timestamp"])
        follow = [
            i for i in incidents
            if i["village"] == alert["village"] and 0 <= (_t(i["timestamp"]) - at).total_seconds() <= window_s
        ]
        lead = None
        if follow:
            lead = round((_t(follow[0]["timestamp"]) - at).total_seconds() / 60, 1)
        rows.append({
            "id": alert["id"],
            "timestamp": alert["timestamp"],
            "village": alert["village"],
            "animal": alert["animal"],
            "tier": alert["tier"],
            "correct": bool(follow),
            "lead_minutes": lead,
        })

    detected, leads = 0, []
    incident_rows = []
    for incident in incidents:
        it = _t(incident["timestamp"])
        earlier = [
            a for a in rows
            if a["village"] == incident["village"] and 0 <= (it - _t(a["timestamp"])).total_seconds() <= window_s
        ]
        warned = bool(earlier)
        lead = None
        if warned:
            detected += 1
            lead = round((it - _t(earlier[0]["timestamp"])).total_seconds() / 60, 1)
            leads.append(lead)
        incident_rows.append({**incident, "warned": warned, "lead_minutes": lead})

    true_alerts = sum(1 for r in rows if r["correct"])
    false_alerts = len(rows) - true_alerts

    stamps = [_t(a["timestamp"]) for a in alerts] + [_t(i["timestamp"]) for i in incidents]
    span_days = max((max(stamps) - min(stamps)).total_seconds() / 86400, 1.0) if stamps else 1.0

    by_tier = {}
    for tier in ("Watch", "Warning", "Imminent"):
        tier_rows = [r for r in rows if r["tier"] == tier]
        by_tier[tier] = {
            "alerts": len(tier_rows),
            "precision": round(sum(1 for r in tier_rows if r["correct"]) / len(tier_rows), 3) if tier_rows else None,
        }

    events = db.list_events()
    verification = {}
    for event in events:
        v = event.get("verification")
        if v in ("auto", "pending", "confirmed", "rejected"):
            verification[v] = verification.get(v, 0) + 1
    suppressed = sum(
        1 for n in db.list_notifications(limit=5000)
        if n.get("channel", "sms") == "sms" and n["status"] == "suppressed"
    )

    return {
        "window_min": window_min,
        "alerts": len(rows),
        "incidents": len(incidents),
        "true_alerts": true_alerts,
        "false_alerts": false_alerts,
        "precision": round(true_alerts / len(rows), 3) if rows else None,
        "recall": round(detected / len(incidents), 3) if incidents else None,
        "median_lead_minutes": round(median(leads), 1) if leads else None,
        "min_lead_minutes": min(leads) if leads else None,
        "false_alarms_per_week": round(false_alerts / (span_days / 7), 1) if rows else None,
        "span_days": round(span_days, 1),
        "by_tier": by_tier,
        "verification": verification,
        "suppressed_duplicates": suppressed,
        "alert_rows": rows[-60:][::-1],
        "incident_rows": incident_rows[-30:][::-1],
    }
