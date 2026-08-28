from typing import Any, Dict

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
