import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.services.budget import (
    BudgetEvaluation,
    BudgetListResult,
    BudgetStatus,
    BudgetStatusResult,
)
from app.services.dispatcher import _handle_budget_query, _register_single_with_hint
from app.services.finance import MovementRegistrationResult


def budget_status(
    *,
    category="Comida",
    limit="1000",
    spent="400",
    remaining="600",
    exceeded="0",
    percentage="40.0",
    state="available",
):
    return BudgetStatus(
        limit_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        category_id=str(uuid.uuid4()),
        category_name=category,
        currency="ARS",
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        limit_amount=Decimal(limit),
        spent_amount=Decimal(spent),
        remaining_amount=Decimal(remaining),
        exceeded_amount=Decimal(exceeded),
        percentage=Decimal(percentage),
        state=state,
    )


@pytest.mark.asyncio
async def test_budget_query_for_category_returns_consumed_and_available():
    status = budget_status()
    with (
        patch(
            "app.services.dispatcher._user_id_by_phone",
            return_value=uuid.uuid4(),
        ),
        patch(
            "app.services.dispatcher.BudgetService.get_status",
            return_value=BudgetStatusResult("ok", "found", status),
        ) as get_status,
    ):
        reply = await _handle_budget_query(
            "5491111111111",
            {
                "limit_category": "Comida",
                "limit_month": 9,
                "limit_year": 2026,
                "limit_currency": "ARS",
            },
        )

    assert "Gastaste $400,00 ARS de $1.000,00 ARS" in reply
    assert "Te quedan $600,00 ARS" in reply
    assert "40.0% usado" in reply
    assert get_status.call_args.args[2] == date(2026, 9, 1)


@pytest.mark.asyncio
async def test_budget_query_without_category_lists_all_budgets():
    statuses = [
        budget_status(),
        budget_status(
            category="Transporte",
            spent="1200",
            remaining="0",
            exceeded="200",
            percentage="120.0",
            state="exceeded",
        ),
    ]
    with (
        patch(
            "app.services.dispatcher._user_id_by_phone",
            return_value=uuid.uuid4(),
        ),
        patch(
            "app.services.dispatcher.BudgetService.list_statuses",
            return_value=BudgetListResult("ok", "found", statuses),
        ),
    ):
        reply = await _handle_budget_query(
            "5491111111111",
            {"limit_month": 9, "limit_year": 2026},
        )

    assert "Comida" in reply
    assert "Transporte" in reply
    assert "Superaste el límite en $200,00 ARS" in reply


@pytest.mark.asyncio
async def test_budget_query_reports_missing_limit():
    with (
        patch(
            "app.services.dispatcher._user_id_by_phone",
            return_value=uuid.uuid4(),
        ),
        patch(
            "app.services.dispatcher.BudgetService.get_status",
            return_value=BudgetStatusResult("not_found", "not found"),
        ),
    ):
        reply = await _handle_budget_query(
            "5491111111111",
            {
                "limit_category": "Comida",
                "limit_month": 9,
                "limit_year": 2026,
            },
        )

    assert reply == "No tenés un límite de Comida para Septiembre en ARS."


@pytest.mark.asyncio
async def test_budget_query_with_year_but_no_month_asks_for_month():
    reply = await _handle_budget_query(
        "5491111111111",
        {"limit_year": 2026, "limit_month": None},
    )

    assert reply == "¿Para qué mes querés consultar el presupuesto?"


@pytest.mark.asyncio
async def test_registered_expense_appends_excess_alert():
    movement_id = str(uuid.uuid4())
    exceeded = budget_status(
        spent="1200",
        remaining="0",
        exceeded="200",
        percentage="120.0",
        state="exceeded",
    )
    movement = {
        "intent": "expense",
        "movement_type": "egreso",
        "amount": 1200,
        "currency": "ARS",
        "description": "supermercado",
        "category": "Comida",
    }
    with (
        patch(
            "app.services.dispatcher.FinanceService.register_movement_with_category",
            return_value=MovementRegistrationResult(
                status="registered",
                message="ok",
                movement_id=movement_id,
                user_id=str(uuid.uuid4()),
            ),
        ),
        patch(
            "app.services.dispatcher.BudgetService.evaluate_movement",
            return_value=BudgetEvaluation(
                status="ok",
                message="evaluated",
                movement_id=movement_id,
                has_limit=True,
                should_alert=True,
                budget=exceeded,
            ),
        ),
        patch(
            "app.services.dispatcher.ConversationService.set_last_movement",
            new_callable=AsyncMock,
        ),
    ):
        reply = await _register_single_with_hint(
            "5491111111111",
            "wamid.1",
            "gasté 1200 en supermercado",
            movement,
            movement,
        )

    assert "Registré tu egreso" in reply
    assert "Superaste el límite en $200,00 ARS" in reply
