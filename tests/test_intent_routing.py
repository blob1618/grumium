from datetime import date
from decimal import Decimal

from app.services.conversation import LastCreatedLimit
from app.services.intent_routing import normalize_limit_intent, references_recent_limit


def recent_limit() -> LastCreatedLimit:
    return LastCreatedLimit(
        limit_id="limit-1",
        sender_phone="5491111111111",
        category_name="Comida",
        amount=Decimal("40000"),
        month=10,
        year=2026,
        currency="ARS",
    )


def test_plain_limits_is_always_list_limits():
    result = normalize_limit_intent("límites", {"intent": "out_of_scope"})
    assert result["intent"] == "list_limits"


def test_limit_status_is_budget_query_not_list():
    result = normalize_limit_intent(
        "muéstrame el estado de mis límites",
        {"intent": "list_limits"},
    )
    assert result["intent"] == "budget_query"


def test_current_month_references_last_limit():
    result = normalize_limit_intent(
        "que sea para el mes actual",
        {"intent": "create_limit", "limit_month": None, "limit_year": None},
        last_limit=recent_limit(),
        today=date(2026, 9, 6),
    )
    assert result["intent"] == "change_limit"
    assert result["limit_month"] == 9
    assert result["limit_year"] == 2026


def test_unrelated_correction_is_not_forced_to_change_limit():
    assert references_recent_limit("en realidad gasté 5000 en comida") is False
    result = normalize_limit_intent(
        "en realidad gasté 5000 en comida",
        {"intent": "expense"},
        last_limit=recent_limit(),
    )
    assert result["intent"] == "expense"
