from pathlib import Path

PROMPT = Path(__file__).resolve().parent.parent / "prompt.md"


def _prompt_text() -> str:
    return PROMPT.read_text(encoding="utf-8")


def test_prompt_has_binary_clarification_rule():
    text = _prompt_text()
    assert "SI Y SOLO SI" in text or "si y solo si" in text.lower()


def test_prompt_has_contrast_examples_for_clarification():
    text = _prompt_text()
    assert "Pagué algo" in text and "Cobré 200 mil" in text


def test_prompt_has_multiop_example():
    text = _prompt_text()
    assert '"movements"' in text
    # dos movimientos dentro del ejemplo multiop
    section = text.split('"movements"', 1)[1][:800]
    assert section.count('"movement_type"') >= 2


def test_prompt_categories_reference_context_list():
    text = _prompt_text().lower()
    assert "lista provista" in text or "categorías provistas" in text
    assert "'servicios' o 'luz'" not in text  # regla difusa eliminada
