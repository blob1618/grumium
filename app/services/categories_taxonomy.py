import unicodedata
from collections.abc import Iterable

DEFAULT_TAXONOMY: dict[str, tuple[str, ...]] = {
    "Servicios": ("servicios", "luz", "electricidad", "agua", "gas", "internet", "wifi", "telefono", "cable"),
    "Comida": ("comida", "alimentacion", "alimentos", "super", "supermercado", "despensa"),
    "Transporte": ("transporte", "nafta", "combustible", "gasolina", "colectivo", "uber", "taxi", "subtes"),
    "Ocio": ("ocio", "salidas", "entretenimiento", "cine"),
    "Vivienda": ("vivienda", "alquiler", "renta", "expensas", "inmobiliaria"),
    "Salud": ("salud", "farmacia", "medicina", "consulta"),
    "Ingresos": ("ingresos", "sueldo", "salario", "sueldos", "haberes"),
    "Educacion": ("educacion", "estudios", "colegio", "universidad", "cursos"),
    "Ropa": ("ropa", "indumentaria", "vestimenta", "calzado"),
}


def _normalize(name: str | None) -> str:
    if name is None:
        return ""
    decomposed = unicodedata.normalize("NFKD", name.strip().lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_SYNONYM_TO_CANONICAL: dict[str, str] = {
    _normalize(synonym): canonical for canonical, synonyms in DEFAULT_TAXONOMY.items() for synonym in synonyms
}


def resolve_category(name: str | None, user_category_names: set[str] | None = None) -> str | None:
    normalized = _normalize(name)
    if not normalized:
        return None

    if normalized in _SYNONYM_TO_CANONICAL:
        return _SYNONYM_TO_CANONICAL[normalized]

    user_names: Iterable[str] = user_category_names or set()
    for raw in user_names:
        if _normalize(raw) == normalized:
            return name

    return None
