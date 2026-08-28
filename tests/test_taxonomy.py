from app.services.categories_taxonomy import resolve_category


def test_resolve_synonym_to_canonical():
    assert resolve_category("luz") == "Servicios"
    assert resolve_category("ALIMENTACIÓN") == "Comida"
    assert resolve_category("  nafta ") == "Transporte"


def test_resolve_canonical_itself():
    assert resolve_category("servicios") == "Servicios"


def test_unknown_returns_none():
    assert resolve_category("cryptomoneda") is None
    assert resolve_category(None) is None


def test_user_custom_category_wins_over_none():
    assert resolve_category("Viáticos", user_category_names={"viáticos"}) == "Viáticos"


def test_taxonomy_beats_custom_on_collision():
    # sinónimo de taxonomía aunque el usuario tenga custom parecido distinto
    assert resolve_category("comida", user_category_names={"Alimentos"}) == "Comida"


def test_accent_and_case_insensitivity():
    assert resolve_category("ALQUILER") == "Vivienda"
    assert resolve_category("Expensas") == "Vivienda"
    assert resolve_category("ócio") == "Ocio"
    assert resolve_category("  SUELDO ") == "Ingresos"
