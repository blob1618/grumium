import pytest
from app.services.llm_contract import normalize_llm_response


def test_normalize_accepts_dict():
    assert normalize_llm_response({"intent": "expense"})["intent"] == "expense"


def test_normalize_rejects_list():
    with pytest.raises(ValueError):
        normalize_llm_response([{"intent": "expense"}])


def test_normalize_rejects_string():
    with pytest.raises(ValueError):
        normalize_llm_response("{\"intent\": \"expense\"}")


def test_normalize_rejects_none():
    with pytest.raises(ValueError):
        normalize_llm_response(None)
