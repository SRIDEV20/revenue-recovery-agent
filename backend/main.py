"""
FastAPI backend for the Revenue Recovery Agent dashboard.

Routes:
  GET  /api/health/timeseries          - payment health time series (optionally filtered)
  GET  /api/health/events              - detected degradation events + root cause statements
  POST /api/pipeline/diagnose          - (re)run Steps 1-6: detect + diagnose + link + persist
  POST /api/pipeline/inject-and-detect - inject a fresh random degradation, then re-run
                                          Steps 1-6 blind against it (live demo trigger)
  POST /api/pipeline/run/{policy}      - run Step 7-10 for 'agent' or 'baseline', persist results
  GET  /api/pipeline/progress          - poll progress of an in-flight agent batch run
  GET  /api/metrics                    - agent vs baseline metrics (overall + degradation-linked)
  GET  /api/decisions                  - paginated decision feed
  GET  /api/escalations                - escalation queue
  GET  /api/audit-log                  - queryable audit trail
  GET  /api/audit-log/export           - full audit trail as downloadable JSON

Every mutating route (diagnose / inject-and-detect / run) is serialized through a
single process-wide lock (_pipeline_lock) - they all read+write the same CSVs/DB, so
two of them running concurrently (e.g. a double-click, or a stale browser tab retrying
after a refresh) could interleave writes and corrupt state. A second request while one
is in flight gets a clean 409, not a race.
"""

import os
import sys
import json
import threading
import traceback
from typing import Optional
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from db import get_connection, init_db as _init_db, clear_run_tables
import pipeline
from diagnosis.affected_transactions import link_transactions_to_all_events
from metrics.evaluate import compute_metrics
from executor import audit_log as audit_log_module
from monitoring.degradation_injector import inject_random_degradation

app = FastAPI(title="Revenue Recovery Agent API", version="1.0.0")

# Comma-separated list of allowed frontend origins, e.g.
# "http://localhost:5173,https://my-app.vercel.app" - set via ALLOWED_ORIGINS
# in the deployment environment. Never falls back to "*" so credentials'd
# requests still work and only known frontends can call this API.
_allowed_origins = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Last-resort safety net so a bug anywhere in the pipeline surfaces as a clean
    # JSON error to the frontend instead of a bare-text 500 / stack trace.
    #
    # Registering a handler for the base Exception class intercepts the request
    # BEFORE Starlette's own ServerErrorMiddleware would - which is what normally
    # logs the traceback to the console. Without this explicit print, an unhandled
    # exception here produces the clean JSON but leaves NOTHING in the server logs
    # to debug from (this bit us once already - a real crash left no trace).
    print(f"[unhandled] {request.method} {request.url.path} -> {type(exc).__name__}: {exc}",
          file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    return JSONResponse(status_code=500, content={"error": f"{type(exc).__name__}: {exc}"})


# in-memory cache of the last diagnosis run (events + linked transactions) so
# run/{policy} doesn't need to re-detect events on every call
_last_diagnosis = {"events": None, "linked": None}

# guards every mutating pipeline route against overlapping runs (double-click, a
# second browser tab, a stale tab retrying after a refresh mid-run, ...)
_pipeline_lock = threading.Lock()
_pipeline_busy_with = {"op": None}

# progress of the current (or most recent) agent batch, polled by the frontend while
# "3. Run agent" is in flight - there's no other channel back to the client mid-request
_agent_progress = {"done": 0, "total": 0, "running": False}


def _acquire_pipeline(op_name: str):
    if not _pipeline_lock.acquire(blocking=False):
        raise HTTPException(
            409, f"Another pipeline operation ('{_pipeline_busy_with['op']}') is already "
                 f"running - wait for it to finish before starting '{op_name}'."
        )
    _pipeline_busy_with["op"] = op_name


def _release_pipeline():
    _pipeline_busy_with["op"] = None
    _pipeline_lock.release()


def _load_diagnosis_from_db() -> Optional[dict]:
    """Reconstructs the {events, linked} shape run_decision_batch() needs directly
    from already-persisted DB rows, with NO inserts - used when the in-memory
    _last_diagnosis cache is empty (e.g. after a backend restart) but the DB already
    holds a completed diagnosis. Re-running run_health_and_diagnosis() in that
    situation would re-INSERT the same transaction_ids and crash on the primary key;
    this reads what's already there instead. Returns None if there's nothing to load."""
    conn = get_connection()
    try:
        event_rows = [dict(r) for r in conn.execute(
            "SELECT * FROM degradation_events ORDER BY event_id").fetchall()]
        txn_rows = [dict(r) for r in conn.execute("SELECT * FROM transactions").fetchall()]
    finally:
        conn.close()

    if not txn_rows:
        return None

    raw_events = [{
        "payment_method": e["payment_method"], "bank_gateway": e["bank_gateway"],
        "window_start": e["window_start"], "window_end": e["window_end"],
        "baseline_rate": e["baseline_rate"], "current_rate": e["current_rate"],
        "severity": e["severity"], "z_score": e["z_score"],
    } for e in event_rows]
    events_with_context = [
        {**raw, "root_cause_statement": e["root_cause_statement"], "event_id": e["event_id"]}
        for raw, e in zip(raw_events, event_rows)
    ]

    txn_df = pd.DataFrame(txn_rows)
    txn_df["timestamp"] = pd.to_datetime(txn_df["timestamp"])
    linked = link_transactions_to_all_events(txn_df, raw_events)
    linked["degradation_linked"] = linked["linked_to_event"]

    return {"events": events_with_context, "linked": linked}


@app.on_event("startup")
def _ensure_db():
    # Render's free-tier filesystem is ephemeral - the SQLite file is wiped on every
    # redeploy and on any restart after the instance spins down from inactivity. So a
    # missing DB file here isn't just a first-run thing, it's the normal case in
    # production. Re-seed it from the committed CSVs immediately so the dashboard
    # never comes up empty - the user shouldn't have to click "1. Diagnose" by hand
    # just to recover from a routine restart. See docs/DEPLOYMENT.md.
    db_path = os.path.join(os.path.dirname(__file__), "revenue_recovery.db")
    if not os.path.exists(db_path):
        _init_db(reset=True)
        diag = pipeline.run_health_and_diagnosis()
        _last_diagnosis["events"] = diag["events"]
        _last_diagnosis["linked"] = diag["linked"]


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/health/timeseries")
def get_health_timeseries(
    payment_method: Optional[str] = None,
    bank_gateway: Optional[str] = None,
    limit: int = Query(default=20000, le=20000),
):
    conn = get_connection()
    try:
        query = "SELECT * FROM payment_health WHERE 1=1"
        params = []
        if payment_method:
            query += " AND payment_method = ?"
            params.append(payment_method)
        if bank_gateway:
            query += " AND bank_gateway = ?"
            params.append(bank_gateway)
        query += " ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/health/slices")
def get_health_slices():
    """Distinct payment_method / bank_gateway combos, for populating filter dropdowns."""
    conn = get_connection()
    try:
        methods = [r[0] for r in conn.execute(
            "SELECT DISTINCT payment_method FROM payment_health ORDER BY 1").fetchall()]
        gateways = [r[0] for r in conn.execute(
            "SELECT DISTINCT bank_gateway FROM payment_health ORDER BY 1").fetchall()]
        return {"payment_methods": methods, "bank_gateways": gateways}
    finally:
        conn.close()


@app.get("/api/health/events")
def get_degradation_events():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM degradation_events ORDER BY window_start ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/pipeline/diagnose")
def run_diagnosis(reset: bool = True):
    """Runs Steps 1-6 (health monitor -> anomaly detector -> root cause -> linking) and
    persists everything. Must run before /api/pipeline/run/{policy}.

    Always clears the run tables before inserting, regardless of `reset` - inserting
    into a DB that already has this run's rows (e.g. called twice, or called after
    /run/{policy} already loaded state) would crash on the transactions primary key.
    `reset=True` (the default, and what the dashboard always sends) additionally drops
    and recreates the whole DB file; `reset=False` just clears rows and keeps the file."""
    _acquire_pipeline("diagnose")
    try:
        if reset:
            _init_db(reset=True)
        else:
            clear_run_tables()
        diag = pipeline.run_health_and_diagnosis()
        _last_diagnosis["events"] = diag["events"]
        _last_diagnosis["linked"] = diag["linked"]
        return {
            "events_detected": len(diag["events"]),
            "events": diag["events"],
            "transactions_linked": int(diag["linked"].degradation_linked.sum()),
            "transactions_total": len(diag["linked"]),
        }
    finally:
        _release_pipeline()


def _match_injected_event(ground_truth: dict, events: list[dict]) -> Optional[dict]:
    """Finds the event (if any) the detector independently flagged for the slice/window
    we just injected - matched by slice + overlapping window, never by trusting the
    injector's numbers directly. Returns None if the detector missed it."""
    gt_start = datetime.fromisoformat(ground_truth["window_start"])
    gt_end = datetime.fromisoformat(ground_truth["window_end"])
    candidates = []
    for e in events:
        if e["payment_method"] != ground_truth["payment_method"] or e["bank_gateway"] != ground_truth["bank_gateway"]:
            continue
        e_start = datetime.fromisoformat(e["window_start"])
        e_end = datetime.fromisoformat(e["window_end"])
        if e_start < gt_end and e_end > gt_start:  # overlap
            candidates.append(e)
    if not candidates:
        return None
    candidates.sort(key=lambda e: abs((datetime.fromisoformat(e["window_start"]) - gt_start).total_seconds()))
    return candidates[0]


@app.post("/api/pipeline/inject-and-detect")
def inject_and_detect():
    """Injects a fresh, randomized degradation event (ground truth kept aside), then
    re-runs the full detection + root-cause pipeline blind against the updated data -
    same as a real anomaly appearing. Resets and re-persists the DB from the CSVs
    (which now hold this new event plus every previously injected one, plus the
    original seed anomaly) so '2. Run baseline' / '3. Run agent' pick everything up."""
    _acquire_pipeline("inject-and-detect")
    try:
        ground_truth = inject_random_degradation()

        _init_db(reset=True)
        diag = pipeline.run_health_and_diagnosis()
        _last_diagnosis["events"] = diag["events"]
        _last_diagnosis["linked"] = diag["linked"]

        detected_event = _match_injected_event(ground_truth, diag["events"])

        return {
            "detected": detected_event,
            "detected_correctly": detected_event is not None,
            "ground_truth": ground_truth,
            "all_events": diag["events"],
        }
    finally:
        _release_pipeline()


@app.post("/api/pipeline/run/{policy}")
def run_policy_batch(policy: str):
    if policy not in ("agent", "baseline"):
        raise HTTPException(400, "policy must be 'agent' or 'baseline'")

    _acquire_pipeline(f"run/{policy}")
    try:
        if _last_diagnosis["events"] is None:
            # cache is empty (e.g. fresh backend restart) - prefer loading what's
            # already persisted in the DB over re-running diagnosis, which would
            # re-insert the same rows and crash. Only run a fresh diagnosis (from
            # the CSVs) if the DB is truly empty too - i.e. nothing has ever run.
            diag = _load_diagnosis_from_db()
            if diag is None:
                diag = pipeline.run_health_and_diagnosis()
            _last_diagnosis["events"] = diag["events"]
            _last_diagnosis["linked"] = diag["linked"]

        if not _last_diagnosis["events"]:
            raise HTTPException(
                400, "No degradation events to run against yet - click '1. Diagnose' first."
            )

        progress_cb = None
        if policy == "agent":
            _agent_progress.update(done=0, total=len(_last_diagnosis["linked"]), running=True)

            def progress_cb(done, total):
                _agent_progress.update(done=done, total=total, running=True)

        try:
            outcomes = pipeline.run_decision_batch(
                policy, _last_diagnosis["events"], _last_diagnosis["linked"],
                progress_callback=progress_cb,
            )
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        finally:
            if policy == "agent":
                _agent_progress["running"] = False

        return {"policy": policy, "transactions_processed": len(outcomes)}
    finally:
        _release_pipeline()


@app.get("/api/pipeline/progress")
def get_agent_progress():
    """Polled by the frontend while '3. Run agent' is in flight, since a single
    blocking POST has no other way to report incremental progress."""
    return dict(_agent_progress)


@app.get("/api/metrics")
def get_metrics():
    return compute_metrics()


@app.get("/api/decisions")
def get_decisions(
    policy: Optional[str] = None,
    degradation_linked: Optional[bool] = None,
    page: int = 1,
    page_size: int = 25,
):
    conn = get_connection()
    try:
        query = """
            SELECT d.*, t.amount, t.failure_type, t.customer_history, t.payment_method,
                   t.bank_gateway, a.action_type, a.allowed, a.block_reason,
                   o.success, o.amount_recovered, o.net_recovered
            FROM decisions d
            JOIN transactions t ON d.transaction_id = t.transaction_id
            LEFT JOIN actions_taken a ON a.decision_id = d.decision_id
            LEFT JOIN outcomes o ON o.action_id = a.action_id
            WHERE 1=1
        """
        params = []
        if policy:
            query += " AND d.policy = ?"
            params.append(policy)
        if degradation_linked is not None:
            query += " AND d.degradation_linked = ?"
            params.append(int(degradation_linked))
        query += " ORDER BY d.decision_id DESC LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])

        rows = conn.execute(query, params).fetchall()

        count_query = "SELECT COUNT(*) FROM decisions d WHERE 1=1"
        count_params = []
        if policy:
            count_query += " AND d.policy = ?"
            count_params.append(policy)
        if degradation_linked is not None:
            count_query += " AND d.degradation_linked = ?"
            count_params.append(int(degradation_linked))
        total = conn.execute(count_query, count_params).fetchone()[0]

        return {
            "items": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    finally:
        conn.close()


@app.get("/api/escalations")
def get_escalation_queue(policy: Optional[str] = "agent"):
    conn = get_connection()
    try:
        query = """
            SELECT d.transaction_id, d.policy, d.reasoning, d.confidence, d.created_at,
                   t.amount, t.failure_type, t.customer_history, t.payment_method,
                   t.bank_gateway, t.retry_count_so_far, a.block_reason
            FROM decisions d
            JOIN transactions t ON d.transaction_id = t.transaction_id
            JOIN actions_taken a ON a.decision_id = d.decision_id
            WHERE a.action_type = 'escalate'
        """
        params = []
        if policy:
            query += " AND d.policy = ?"
            params.append(policy)
        query += " ORDER BY t.amount DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/audit-log")
def get_audit_log(
    transaction_id: Optional[str] = None,
    stage: Optional[str] = None,
    policy: Optional[str] = None,
    limit: int = Query(default=200, le=2000),
    offset: int = 0,
):
    return audit_log_module.get_log(
        transaction_id=transaction_id, stage=stage, policy=policy, limit=limit, offset=offset
    )


@app.get("/api/audit-log/export")
def export_audit_log():
    payload = audit_log_module.export_json()
    return JSONResponse(content=json.loads(payload), headers={
        "Content-Disposition": "attachment; filename=audit_log.json"
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
