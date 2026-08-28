from typing import Any, Dict

from pydantic import BaseModel, Field


class MovementContract(BaseModel):
    model_config = {"extra": "ignore"}
    intent: str | None = None
    movement_type: str | None = None
    amount: float | None = None
    currency: str | None = None
    category: str | None = None
    description: str | None = None
    expense: str | None = None
    reply_text: str | None = None


RETRY_FORMAT_INSTRUCTION = (
    "\n\nIMPORTANTE: Respondé ÚNICAMENTE con un objeto JSON válido, "
    "no con una lista ni texto adicional."
)


def normalize_llm_response(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(
            f"LLM output non-conformant: expected object, got {type(raw).__name__}"
        )
    return raw
