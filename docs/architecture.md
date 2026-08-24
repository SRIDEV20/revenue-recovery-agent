# Architecture

Revenue Recovery Agent implements one continuous pipeline: **payment degradation → root cause → recovery**. Every stage below is a real, runnable module — nothing here is a mock diagram of a system that doesn't exist.

```
Time-series transaction data (by payment_method x bank/gateway x time window)
        |
Payment Health Monitoring (rolling success rate, latency, volume per slice)
        |
Detect Degradation (anomaly scoring vs rolling baseline)
        |
Root Cause Analysis (isolate which slice/dimension is degrading, and why)
        |
Identify Affected Transactions (pull actual failed txns in that slice/window)
        |
AI Recovery Agent (per-transaction decision: retry/delay/discount/reroute/escalate, with reasoning)
        |
Stopping Rules (retry caps, cooldowns, discount caps, escalation triggers)
        |
Mock Recovery Execution (simulated outcome per action)
        |
Outcome -> Revenue Recovered
        |
Agent vs Baseline (baseline retries blindly during outage; agent waits/reroutes)
        |
Dashboard + Audit Trail
```

## Stage-by-stage

### 1. Time-series transaction data
`backend/data/generate_timeseries_dataset.py` produces `payment_health.csv`: hourly `success_rate`, `avg_latency_ms`, `transaction_volume` for every (payment_method x bank_gateway) slice over 14 days. One deliberate anomaly is injected — UPI on "PayFast Gateway" drops from ~94% to ~68% over an 8-hour window on Day 6 — everything else stays in healthy-noise range (94-98%). The injection code is commented inline (`# INJECTED ANOMALY`) so it's trivial to point to in a demo.

`backend/data/generate_transactions.py` produces `failed_transactions.csv`: ~280 individual failed/at-risk transactions. A cluster of ~140 falls inside the injected degradation window/slice; the rest are an unrelated baseline population (card expired, insufficient funds, cart abandonment, invoice overdue, etc.). Each transaction carries hidden ground-truth fields (`ground_truth_recovery_probability`, and a post-recovery variant) used only for outcome simulation and evaluation — never shown to the agent.

### 2. Payment health monitoring
`backend/monitoring/health_monitor.py` computes, for every slice and hour, a trailing 48-hour rolling baseline success rate (and std dev), excluding the current hour — "what's normal for this slice right now."

### 3. Detect degradation
`backend/monitoring/anomaly_detector.py` flags a slice as degraded when its current window drops >=15 percentage points below its rolling baseline, or its z-score exceeds 3.0, sustained for >=3 consecutive hours (to reject single-hour noise). Contiguous breaching hours are merged into one `degradation_event`.

### 4. Root cause analysis
`backend/diagnosis/root_cause.py` takes a flagged event and checks whether the drop is isolated: are other gateways for the same payment method healthy in the same window? Is the same gateway healthy for other payment methods? Is the rest of the platform healthy? This produces a classification (`gateway_specific_issue`, `payment_method_wide_issue`, `gateway_wide_issue`, `platform_wide_incident`) and a human-readable statement, e.g.:

> "UPI success rate on PayFast Gateway dropped from 95% to 74% between 13:00-19:00 on Aug 13, while other gateways remained stable — indicates a PayFast Gateway-specific issue, not a UPI-wide problem."

### 5. Identify affected transactions
`backend/diagnosis/affected_transactions.py` re-derives which real transactions fall inside the detected event's slice + window (independently of the seed data's ground-truth label — the pipeline discovers this the same way it would against production data).

### 6. AI Recovery Agent
`backend/agent/decision_engine.py` calls the OpenAI API (`gpt-4o-mini`, structured outputs via `response_format: json_schema`) once per transaction. If the transaction is degradation-linked, it receives the root-cause statement as context. The system prompt (`backend/agent/prompts.py`) instructs the model to prefer `retry_delayed` or `reroute_gateway` over `retry_now` for transactions still inside an active outage — retrying into a known-degraded gateway is close to guaranteed to fail again.

`backend/agent/baseline_policy.py` is the control group: a naive, degradation-blind policy that retries every failure once, immediately, regardless of gateway health.

### 7. Stopping rules
`backend/executor/stopping_rules.py` enforces, in code (not just prompted): max 3 retries, 4-hour minimum cooldown on delayed retries, 15% discount cap, and forced escalation when `retry_count_so_far >= 2 and failure_type == bank_decline`. This runs on both policies' decisions and can override them.

### 8. Mock recovery execution
`backend/executor/actions.py` simulates the outcome of each allowed action using the transaction's hidden ground-truth recovery probability, adjusted per action type (a delayed retry after an outage recovers uses the post-recovery probability; a discount/reminder/escalation applies a fixed uplift). Nothing calls a real payment gateway.

### 9. Outcome -> revenue recovered / Agent vs baseline
`backend/metrics/evaluate.py` aggregates net revenue recovered, recovery rate, cost-to-recover per Rs.100, and escalation count — for each policy, both overall and restricted to degradation-linked transactions. The degradation-linked breakout is the number that isolates the root-cause layer's value: baseline keeps retrying into the outage and failing, while the agent waits or reroutes.

### 10. Dashboard + audit trail
`backend/executor/audit_log.py` appends a row for every decision, rule check, action, and outcome — queryable and exportable as JSON. The React dashboard (`frontend/`) surfaces the health timeline with the degradation window marked, the root cause statement, agent-vs-baseline recovery charts, a live decision feed with reasoning, and the escalation queue.

## Data flow / storage

All of the above is persisted to SQLite (`backend/db.py`): `payment_health`, `transactions`, `degradation_events`, `decisions`, `actions_taken`, `outcomes`, `audit_log`. The schema is committed; the live `.db` file is not (see `.gitignore`) — it's rebuilt by running the pipeline.

`backend/pipeline.py` is the orchestrator that wires every stage above into two entry points: `run_health_and_diagnosis()` (steps 1-5) and `run_decision_batch(policy)` (steps 6-9, run once per policy). `backend/main.py` exposes both over FastAPI so the dashboard can trigger and read a live run.
