import pytest

from tests.test_llm import _process_message_with_mock_response


@pytest.mark.asyncio
async def test_multiop_message_returns_both_movements():
    mock_response = {
        "intent": "expense",
        "reply_text": "",
        "movements": [
            {"movement_type": "ingreso", "amount": 50000, "currency": "ARS",
             "description": "sueldo", "reply_text": ""},
            {"movement_type": "egreso", "amount": 10000, "currency": "ARS",
             "description": "comida", "reply_text": ""},
        ],
    }
    result = await _process_message_with_mock_response(mock_response)
    assert len(result["movements"]) == 2
    assert result["movements"][0]["movement_type"] == "ingreso"
    assert result["movements"][1]["amount"] == 10000.0


@pytest.mark.asyncio
async def test_single_flat_object_wraps_into_movements_list():
    mock_response = {
        "intent": "expense", "movement_type": "egreso",
        "amount": 5000.0, "currency": "ARS", "description": "super", "reply_text": "",
    }
    result = await _process_message_with_mock_response(mock_response)
    assert len(result["movements"]) == 1
    assert result["movements"][0]["amount"] == 5000.0


@pytest.mark.asyncio
async def test_non_movement_intent_returns_empty_movements():
    mock_response = {"intent": "greeting", "reply_text": "hola"}
    result = await _process_message_with_mock_response(mock_response)
    assert result["movements"] == []


@pytest.mark.asyncio
async def test_invalid_movement_in_list_is_normalized_not_dropped_silently():
    mock_response = {
        "intent": "expense",
        "movements": [
            {"movement_type": "egreso", "amount": 1000, "description": "ok", "reply_text": ""},
            {"movement_type": "egreso", "amount": "no-numero", "description": "malo", "reply_text": ""},
        ],
    }
    result = await _process_message_with_mock_response(mock_response)
    assert len(result["movements"]) == 2
    assert result["movements"][1]["amount"] is None  # normalizado, dispatcher decidirá
