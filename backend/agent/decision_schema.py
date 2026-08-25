"""
Pydantic-backed validation for decision dicts, checked as a defense-in-depth layer
in pipeline.py before a decision (from either policy) is persisted or acted on.

The OpenAI call in decision_engine.py already enforces this same shape via strict
structured outputs, and baseline_policy.py always builds a compliant dict by hand -
but this is the one place BOTH policies' decisions are guaranteed to pass through, so
it is the right layer to catch anything that slips past those (a hand-edited fixture,
a future policy, a schema drift between prompts.py and here).
"""

from typing import Optional

from pydantic import BaseModel, Field, ValidationError

ALLOWED_DECISIONS = {
    "retry_now", "retry_delayed", "send_discount",
    "send_reminder", "reroute_gateway", "escalate", "give_up",
}


class DecisionModel(BaseModel):
    transaction_id: str
    decision: str
    reasoning: str
    confidence: float = Field(ge=0, le=1)
    delay_hours: Optional[int] = None
    discount_pct: Optional[int] = None


def validate_decision(decision: dict) -> dict:
    """Validates a raw decision dict against the required shape. Returns the
    validated fields as a plain dict on success. Raises ValueError if a required
    field is missing/wrong-typed, or if `decision` is not one of ALLOWED_DECISIONS."""
    try:
        model = DecisionModel(**decision)
    except ValidationError as e:
        raise ValueError(f"invalid decision schema: {e}") from e

    if model.decision not in ALLOWED_DECISIONS:
        raise ValueError(
            f"invalid decision schema: decision={model.decision!r} is not one of "
            f"{sorted(ALLOWED_DECISIONS)}"
        )

    return model.model_dump()
