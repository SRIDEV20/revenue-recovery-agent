"""
Real OpenAI API calls for per-transaction recovery decisions.

Each transaction is sent as its own request using OpenAI's structured outputs
(`response_format={"type": "json_schema", ...}`, strict schema) so the response
is always valid JSON matching agent/prompts.py::DECISION_SCHEMA. Uses gpt-4o-mini
since this is a bounded, per-transaction classification/decision task rather than
open-ended reasoning - keeps cost and latency down across a few hundred calls.

Run `python -m agent.decision_engine` to sanity-check on 5 transactions before
running the full batch via metrics/evaluate.py or the FastAPI routes.
"""

import os
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI
from dotenv import load_dotenv

from agent.prompts import SYSTEM_PROMPT, DECISION_SCHEMA, build_transaction_prompt

load_dotenv()

MODEL = "gpt-4o-mini"
MAX_WORKERS = 6

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": DECISION_SCHEMA["name"],
        "description": DECISION_SCHEMA["description"],
        "schema": {
            **DECISION_SCHEMA["input_schema"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


def _get_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to backend/.env (see .env.example) "
            "or export it in your shell before running the decision engine."
        )
    return OpenAI(api_key=api_key)


def decide_single(client: OpenAI, txn: dict, root_cause_context: str | None) -> dict:
    """Makes ONE OpenAI API call for one transaction, returns the parsed decision dict."""
    prompt = build_transaction_prompt(txn, root_cause_context)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format=RESPONSE_FORMAT,
    )

    choice = response.choices[0]
    content = choice.message.content
    if not content:
        raise RuntimeError(
            f"No content returned for {txn['transaction_id']}: finish_reason={choice.finish_reason}"
        )

    decision = json.loads(content)
    # Always trust OUR OWN transaction_id, never the model's echoed copy - the schema
    # requires the model to reproduce it, but LLMs are unreliable at exact
    # character-for-character reproduction of opaque hex/uuid strings (they can
    # truncate or subtly mangle them). A silently-wrong id here caused a downstream
    # KeyError in pipeline.py (which looks transactions up by this value) once in
    # ~600+ live decisions - overriding unconditionally closes that off entirely
    # rather than only patching the rare case where the model omits the field.
    decision["transaction_id"] = txn["transaction_id"]
    return decision


def _fallback_decision(txn: dict, error: Exception) -> dict:
    """Used when a single transaction's OpenAI call fails (rate limit, network error,
    malformed response, ...) - the rest of the batch must keep going, so this txn is
    flagged for a human instead of taking down the whole run."""
    return {
        "transaction_id": txn["transaction_id"],
        "decision": "escalate",
        "reasoning": f"AI decision failed ({type(error).__name__}: {error}); flagged for manual review.",
        "confidence": 0.0,
        "delay_hours": None,
        "discount_pct": None,
    }


def run_batch(transactions: list[dict], root_cause_context_by_txn: dict[str, str],
              max_workers: int = MAX_WORKERS, progress_callback=None) -> list[dict]:
    """
    transactions: list of transaction dicts (must include transaction_id, degradation_linked, ...)
    root_cause_context_by_txn: {transaction_id: root_cause_statement} for degradation-linked txns
    Returns decisions in the SAME ORDER as `transactions`, each tagged with policy='agent'.
    """
    client = _get_client()
    results = [None] * len(transactions)

    def _work(i: int, txn: dict):
        ctx = root_cause_context_by_txn.get(txn["transaction_id"]) if txn.get("degradation_linked") else None
        try:
            decision = decide_single(client, txn, ctx)
        except Exception as e:
            print(f"[decision_engine] {txn['transaction_id']} failed, falling back to escalate: {e}",
                  file=sys.stderr)
            decision = _fallback_decision(txn, e)
        decision["policy"] = "agent"
        decision["degradation_linked"] = bool(txn.get("degradation_linked", False))
        return i, decision

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_work, i, txn) for i, txn in enumerate(transactions)]
        done_count = 0
        for future in as_completed(futures):
            i, decision = future.result()
            results[i] = decision
            done_count += 1
            if progress_callback:
                progress_callback(done_count, len(transactions))

    return results


def _test_five():
    """Loads real transactions + degradation events and runs 5 live decisions end to end."""
    import pandas as pd
    from monitoring.health_monitor import load_health_data, compute_rolling_baseline
    from monitoring.anomaly_detector import detect_degradation_events
    from diagnosis.root_cause import analyze
    from diagnosis.affected_transactions import link_transactions_to_all_events

    health_df = load_health_data()
    enriched = compute_rolling_baseline(health_df)
    events = detect_degradation_events(enriched)
    root_causes = [analyze(e, health_df) for e in events]

    txn_path = os.path.join(os.path.dirname(__file__), "..", "data", "failed_transactions.csv")
    transactions_df = pd.read_csv(txn_path, parse_dates=["timestamp"])
    linked = link_transactions_to_all_events(transactions_df, events)
    linked["degradation_linked"] = linked["linked_to_event"]

    # pick 3 degradation-linked + 2 baseline transactions for a representative test
    degraded_sample = linked[linked.degradation_linked].head(3)
    baseline_sample = linked[~linked.degradation_linked].head(2)
    sample = pd.concat([degraded_sample, baseline_sample])

    context_by_txn = {}
    for _, row in degraded_sample.iterrows():
        idx = row["matched_event_index"]
        context_by_txn[row["transaction_id"]] = root_causes[idx]["root_cause_statement"]

    txns = sample.assign(timestamp=sample.timestamp.astype(str)).to_dict(orient="records")

    client = _get_client()
    for txn in txns:
        ctx = context_by_txn.get(txn["transaction_id"]) if txn["degradation_linked"] else None
        decision = decide_single(client, txn, ctx)
        print(json.dumps({
            "transaction_id": txn["transaction_id"],
            "degradation_linked": txn["degradation_linked"],
            "failure_type": txn["failure_type"],
            **decision,
        }, indent=2))
        print("-" * 60)


if __name__ == "__main__":
    _test_five()
