"""
Append-only audit log. Every decision, rule check, action, and outcome in the
pipeline writes one row here via log_event(). Queryable via get_log() and
exportable as JSON via export_json().
"""

import json
from datetime import datetime

from db import db_session


def log_event(stage: str, detail: dict, transaction_id: str = None, policy: str = None,
              timestamp: str = None, conn=None):
    """
    stage: 'decision' | 'rule_check' | 'action' | 'outcome' | 'escalation' | 'pipeline'
    detail: JSON-serializable dict with the specifics of this event

    Pass `conn` when called from inside an existing db_session() block (e.g. the
    pipeline orchestrator) to avoid opening a second connection mid-transaction,
    which SQLite would reject as a database lock. Without `conn`, opens its own
    short-lived session (fine for standalone/one-off calls).
    """
    ts = timestamp or datetime.utcnow().isoformat()
    sql = "INSERT INTO audit_log (timestamp, transaction_id, policy, stage, detail) VALUES (?, ?, ?, ?, ?)"
    params = (ts, transaction_id, policy, stage, json.dumps(detail, default=str))

    if conn is not None:
        conn.execute(sql, params)
    else:
        with db_session() as new_conn:
            new_conn.execute(sql, params)


def get_log(transaction_id: str = None, stage: str = None, policy: str = None,
            limit: int = 500, offset: int = 0) -> list[dict]:
    query = "SELECT * FROM audit_log WHERE 1=1"
    params = []
    if transaction_id:
        query += " AND transaction_id = ?"
        params.append(transaction_id)
    if stage:
        query += " AND stage = ?"
        params.append(stage)
    if policy:
        query += " AND policy = ?"
        params.append(policy)
    query += " ORDER BY log_id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with db_session() as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["detail"] = json.loads(d["detail"])
        except (TypeError, json.JSONDecodeError):
            pass
        result.append(d)
    return result


def export_json(path: str = None) -> str:
    """Returns the full audit log as a JSON string; optionally writes it to `path`."""
    entries = get_log(limit=1_000_000)
    payload = json.dumps(entries, indent=2, default=str)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)
    return payload
