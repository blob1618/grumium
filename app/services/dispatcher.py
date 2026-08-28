"""
Message dispatcher — routes incoming user messages to the appropriate service.

Extracted from app/main.py so both the WhatsApp webhook and the testing
environment can invoke the same logic.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.sql import func

from app.models.database import Categoria, SessionLocal, Usuario
from app.services.conversation import (
    ConversationService,
    LastCreatedLimit,
    LastRegisteredMovement,
    PendingLimit,
    PendingLimitDelete,
    PendingMovement,
    PendingReminder,
)
from app.services.dashboard_link import DashboardLinkDecision, DashboardLinkService
from app.services.finance import FinanceService, MovementRegistrationResult
from app.services.limit import LimitService
from app.services.llm import LLMService
from app.services.llm_contract import resolve_relative_date
from app.services.onboarding import OnboardingDecision, OnboardingService
from app.services.reminder import ReminderListResult, ReminderResult, ReminderService


@dataclass
class DispatchResult:
    """Result of processing an incoming message."""
    reply_text: str
    raw_llm_response: dict | None = None
    service_invoked: str | None = None
    intent: str | None = None
    debug_info: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Reply helpers
# ---------------------------------------------------------------------------


def _is_financial_movement(extracted_data: dict) -> bool:
    return extracted_data.get("intent") == "expense"


def _movement_description(extracted_data: dict) -> str:
    return (
        extracted_data.get("description")
        or extracted_data.get("expense")
        or "movimiento"
    )


def _format_amount(amount) -> str:
    try:
        decimal_amount = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return str(amount)

    if decimal_amount == decimal_amount.to_integral_value():
        return str(decimal_amount.quantize(Decimal("1")))
    return str(decimal_amount.normalize())


def _registered_reply(extracted_data: dict) -> str:
    movement_type = extracted_data.get("movement_type") or "movimiento"
    description = _movement_description(extracted_data)
    amount = _format_amount(extracted_data.get("amount"))
    currency = str(extracted_data.get("currency") or "ARS").upper()
    return f"✅ Registré tu {movement_type}: {description} por ${amount} {currency}."


def _category_hint_reply() -> str:
    return (
        "¿No estás de acuerdo con la categoría? Indicame y lo cambiamos."
    )


def _category_confirmation_reply(category_name: str) -> str:
    return (
        f"📁 Detecté la categoría *{category_name}*. "
        "¿Confirmás que es correcta? Respondé 'sí' para confirmar o decime la categoría correcta."
    )


def _category_changed_reply(description: str, amount: str, currency: str, category_name: str) -> str:
    return (
        f"✅ Listo, se guardó el {description} por ${amount} {currency} "
        f"con la categoría {category_name}."
    )


def _registration_reply(
    result: MovementRegistrationResult,
    extracted_data: dict,
) -> str:
    if result.status == "registered":
        return _registered_reply(extracted_data)

    if result.status == "duplicate":
        return "Este movimiento ya había sido registrado, no lo dupliqué."

    if result.status == "user_not_found":
        return "No encontré una cuenta vinculada a este WhatsApp. No pude registrar el movimiento."

    if result.status == "invalid_data":
        return (
            "No pude registrar el movimiento porque me faltan datos claros. "
            "¿Podés reenviarlo con monto, descripción y si es ingreso o egreso?"
        )

    if result.status == "persistence_error":
        return "Hubo un problema registrando el movimiento. Por favor, intentá nuevamente en unos minutos."

    if result.status == "not_a_movement":
        return (
            "No identifiqué un movimiento financiero para registrar. "
            "Podés escribir algo como: 'Gasté 5000 en supermercado'."
        )

    return extracted_data.get("reply_text") or "No pude interpretar ese mensaje como un movimiento financiero."


def _registration_dispatch_reply(
    result: MovementRegistrationResult,
    extracted_data: dict,
) -> str:
    """
    Responde al registro. Un duplicado (mismo whatsapp_message_id ya persistido)
    es un reintento/reenvío de Meta de un mensaje ya procesado: la confirmación ya
    se envió en la primera entrega, así que se suprime la respuesta visible.
    """
    if result.status == "duplicate":
        return ""
    return _registration_reply(result, extracted_data)


def _multiop_registration_reply(
    results: list[MovementRegistrationResult],
    extracted_data: dict,
    movements: list | None = None,
) -> str:
    """Resume el registro de uno o varios movimientos por mensaje."""
    registered = sum(1 for r in results if r.status == "registered")
    total = len(results)

    if registered == total:
        if total == 1:
            single = (movements or [extracted_data])[0]
            return _registered_reply(single)
        return f"✅ Registré los {total} movimientos."

    if registered == 0:
        return (
            "No pude registrar ningún movimiento porque me faltan datos. "
            "¿Podés reenviarlos con monto, descripción y si es ingreso o egreso?"
        )

    return (
        f"✅ Registré {registered} de {total} movimientos. "
        "Algunos faltan datos (monto, descripción o tipo). ¿Los reenvías?"
    )


def _safe_non_stk35_reply(extracted_data: dict) -> str:
    intent = extracted_data.get("intent")
    reply_text = extracted_data.get("reply_text") or ""

    # Estos intents se manejan aparte en el flujo STK-39
    if intent in {"confirm_category", "reject_category", "delete_category", "list_categories", "change_category"}:
        return reply_text

    return reply_text or "No pude interpretar tu mensaje. ¿Podés reformularlo?"


def build_user_context(sender_phone: str) -> str:
    """Contexto para el LLM: fecha actual + categorías activas del usuario.

    Degrada silenciosamente (solo fecha) si la BD falla, nunca rompe el flujo.
    """
    date_line = f"FECHA ACTUAL: {date.today().isoformat()}."  # noqa: DTZ011
    session = None
    try:
        session = SessionLocal()
        user = session.query(Usuario).filter(Usuario.whatsapp_id == sender_phone).first()
        if user is None:
            return date_line
        categorias = (
            session.query(Categoria)
            .filter(Categoria.usuario_id == user.id)
            .filter(Categoria.esta_eliminado.is_(False))
            .order_by(Categoria.nombre)
            .all()
        )
    except Exception as exc:
        print(f"[BUILD_USER_CONTEXT] Error: {type(exc).__name__}: {exc}")
        return date_line
    finally:
        if session is not None:
            session.close()

    if not categorias:
        return date_line
    nombres = ", ".join(c.nombre for c in categorias)
    return f"{date_line}\nCATEGORÍAS DISPONIBLES DEL USUARIO: {nombres}"


def _update_ultimo_mensaje(sender_phone: str) -> None:
    """Update usuario.ultimo_mensaje_en for WhatsApp 24h window tracking."""
    from app.models.database import Usuario
    session = SessionLocal()
    try:
        session.query(Usuario).filter(
            Usuario.whatsapp_id == sender_phone
        ).update({"ultimo_mensaje_en": func.now()})
        session.commit()
    except Exception as exc:
        session.rollback()
        print(f"[UPDATE_ULTIMO_MENSAJE] Error: {type(exc).__name__}: {exc}")
    finally:
        session.close()


def _is_create_reminder(extracted_data: dict) -> bool:
    return extracted_data.get("intent") == "create_reminder"


_CONCEPT_EXTRACTOR = re.compile(
    r'(?:recordatorio|avis(?:ar|ame?)|record(?:ar|ame?)|crea(?:r|me)?|quiero)\s+'
    r'(?:(?:de|para|el|la|los|las|un|una|del|al|pagar|crear|hacer|recordatorio)\s+)*'
    r'(\w[\w\s]{0,30}?\w)'
    r'(?=\s+(?:el\s+)?(?:d[ií]a|\d)|$)',
    re.IGNORECASE,
)

_VERBOS_ACCION = re.compile(r'\b(pagar|crear|quiero|crees|hacer|avisar|recordar)\b', re.IGNORECASE)


def _extract_concept_from_text(text: str) -> str | None:
    m = _CONCEPT_EXTRACTOR.search(text)
    if m:
        candidate = m.group(1).strip()
        if 2 <= len(candidate) <= 32:
            return candidate
    return None


def _validate_reminder_concept(llm_concept: str | None, text_body: str) -> str | None:
    if not llm_concept:
        return _extract_concept_from_text(text_body)
    cleaned = llm_concept.strip()
    # force regex if concept smells like a sentence (contains verbs or > 3 words)
    if _VERBOS_ACCION.search(cleaned):
        return _extract_concept_from_text(text_body)
    if len(cleaned) > 32 or len(cleaned.split()) > 3:
        return _extract_concept_from_text(text_body)
    return cleaned


def _reminder_creation_reply(
    result: ReminderResult,
    extracted_data: dict,
) -> str:
    if result.status == "created":
        concept = extracted_data.get("reminder_concept") or "tu pago"
        day = extracted_data.get("reminder_day")
        amount = extracted_data.get("reminder_amount")
        currency = str(extracted_data.get("reminder_currency") or "ARS").upper()
        amount_text = ""
        if amount:
            amount_text = f" (${_format_amount(amount)} {currency})"
        return f"✅ Dale, te aviso que pagués {concept}{amount_text} el día {day} de cada mes."

    if result.status == "duplicate_title":
        return result.message

    if result.status == "user_not_found":
        return "No encontré una cuenta vinculada a este WhatsApp."

    if result.status == "invalid_data":
        return result.message

    if result.status == "persistence_error":
        return "Hubo un problema. Intentá nuevamente en unos minutos."

    return "No pude procesar tu solicitud de recordatorio."


def _reminder_list_reply(result: ReminderListResult) -> str:
    reminders = result.reminders or []
    if not reminders:
        return "No tenés recordatorios activos por ahora."

    lines = ["📌 *Tus recordatorios:*"]
    for reminder in reminders:
        amount = reminder.get("monto")
        currency = str(reminder.get("moneda") or "ARS").upper()
        amount_text = ""
        if amount is not None:
            amount_text = f" — ${_format_amount(amount)} {currency}"
        estado = reminder.get("estado", "activo")
        estado_icon = "⏸️" if estado == "pausado" else ""
        lines.append(
            f"{estado_icon}• *{reminder.get('titulo')}* — día {reminder.get('dia_del_mes')}{amount_text}"
        )
    return "\n".join(lines)


def _reminder_update_reply(result: ReminderResult) -> str:
    if result.status == "updated":
        return "✅ Listo, actualicé el recordatorio."
    if result.status == "user_not_found":
        return "No encontré una cuenta vinculada a este WhatsApp."
    if result.status in {"not_found", "not_owned"}:
        return "No encontré ese recordatorio. Chequeá el nombre con *mis recordatorios*."
    if result.status == "invalid_data":
        return result.message
    if result.status == "persistence_error":
        return "Hubo un problema. Intentá nuevamente en unos minutos."
    return "No pude procesar la edición del recordatorio."


def _reminder_state_reply(result: ReminderResult, action: str) -> str:
    if result.status == action:
        if action == "paused":
            return "✅ Dale, pausé ese recordatorio. Aviáme si querés reactivarlo."
        return "✅ Listo, reactivé el recordatorio."
    if result.status == "user_not_found":
        return "No encontré una cuenta vinculada a este WhatsApp."
    if result.status in {"not_found", "not_owned"}:
        return "No encontré ese recordatorio. Chequeá el nombre con *mis recordatorios*."
    if result.status == "invalid_data":
        return result.message
    if result.status == "persistence_error":
        return "Hubo un problema. Intentá nuevamente en unos minutos."
    return "No pude procesar el cambio de estado del recordatorio."


def _reminder_delete_reply(result: ReminderResult) -> str:
    if result.status == "deleted":
        return "✅ Listo, eliminé el recordatorio."
    if result.status == "user_not_found":
        return "No encontré una cuenta vinculada a este WhatsApp."
    if result.status in {"not_found", "not_owned"}:
        return "No encontré ese recordatorio. Chequeá el nombre con *mis recordatorios*."
    if result.status == "invalid_data":
        return result.message
    if result.status == "persistence_error":
        return "Hubo un problema. Intentá nuevamente en unos minutos."
    return "No pude procesar la eliminación del recordatorio."


async def _handle_list_reminders(sender_phone: str) -> str:
    from app.models.database import SessionLocal, Usuario

    session = SessionLocal()
    try:
        user = session.query(Usuario).filter(Usuario.whatsapp_id == sender_phone).first()
        if user is None:
            return "No encontré tu cuenta."

        result = ReminderService.list_reminders_all(user.id)
        return _reminder_list_reply(result)
    except Exception as exc:
        print(f"[REMINDER_LIST] Error: {type(exc).__name__}: {exc}")
        return "Hubo un problema consultando tus recordatorios."
    finally:
        session.close()


def _onboarding_invitation_reply(registration_url: str, ttl_minutes: int) -> str:
    return (
        "Para usar Luka, primero registrate y vinculá este WhatsApp:\n\n"
        f"{registration_url}\n\n"
        f"El enlace vence en {ttl_minutes} minutos."
    )


def _dashboard_link_reply(login_url: str, ttl_minutes: int) -> str:
    return (
        "Accedé a tu dashboard acá:\n\n"
        f"{login_url}\n\n"
        f"El enlace vence en {ttl_minutes} minutos y sólo se puede usar una vez."
    )


_DASHBOARD_LINK_NOT_ELIGIBLE_REPLY = (
    "Todavía no tenés una cuenta vinculada. Escribime cualquier mensaje para empezar."
)


# ---------------------------------------------------------------------------
# STK-39 v2: Handlers de gestión de categorías
# ---------------------------------------------------------------------------


def _category_deleted_reply(category_name: str) -> str:
    return f"✅ Categoría '{category_name}' eliminada. Los movimientos de esa categoría quedaron sin categoría."


def _category_not_found_reply(category_name: str) -> str:
    return f"No encontré una categoría '{category_name}'."


def _format_categories_list(categories_result) -> str:
    """Formatea la lista de categorías con totales para enviar por WhatsApp."""
    cats = categories_result.categories
    if not cats:
        return "No tenés categorías todavía. Cuando registres movimientos se irán creando."

    lines = ["📊 *Tus categorías:*"]
    for c in cats:
        ingreso = _format_amount(c.total_ingresos)
        egreso = _format_amount(c.total_egresos)
        default_tag = " (por defecto)" if c.es_default else ""
        lines.append(
            f"• {c.category_name}{default_tag}: "
            f"💰 ${ingreso} ingreso | 💸 ${egreso} egreso"
        )
    return "\n".join(lines)


async def _handle_change_category(sender_phone: str, extracted_data: dict) -> str:
    """
    Maneja el cambio de categoría de un movimiento ya registrado.
    """
    from app.models.database import SessionLocal, Usuario

    new_category = extracted_data.get("category")
    if not new_category:
        return "¿A qué categoría querés cambiar el movimiento?"

    # Obtener el último movimiento registrado
    last_movement = await ConversationService.get_last_movement(sender_phone)
    if last_movement is None:
        return "No encontré un movimiento reciente para cambiarle la categoría."

    # Obtener user_id
    session = SessionLocal()
    try:
        user = session.query(Usuario).filter(Usuario.whatsapp_id == sender_phone).first()
        if user is None:
            return "No encontré tu cuenta."
        user_id = user.id
    finally:
        session.close()

    # Actualizar categoría
    result = FinanceService.update_movement_category(
        movement_id=last_movement.movement_id,
        user_id=user_id,
        new_category_name=new_category,
        create_if_missing=True,
    )

    if result.status == "updated":
        # Actualizar el last_movement con la nueva categoría
        last_movement.category_name = new_category
        await ConversationService.set_last_movement(sender_phone, last_movement)

        amount = _format_amount(last_movement.amount)
        currency = last_movement.currency.upper()
        return _category_changed_reply(
            description=last_movement.description,
            amount=amount,
            currency=currency,
            category_name=new_category,
        )
    elif result.status == "not_found":
        return "No encontré el movimiento para cambiarle la categoría."
    else:
        return "Hubo un problema actualizando la categoría. Intentá de nuevo."


async def _handle_delete_category(sender_phone: str, extracted_data: dict) -> str:
    """Maneja la eliminación de una categoría."""
    from app.models.database import SessionLocal, Usuario

    category_name = extracted_data.get("category")
    if not category_name:
        return "¿Qué categoría querés eliminar? Decime el nombre."

    session = SessionLocal()
    try:
        user = session.query(Usuario).filter(Usuario.whatsapp_id == sender_phone).first()
        if user is None:
            return "No encontré tu cuenta."
        user_id = user.id
    finally:
        session.close()

    result = FinanceService.delete_category(user_id, category_name)
    if result.status == "deleted":
        return _category_deleted_reply(result.category_name or category_name)
    elif result.status == "not_found":
        return _category_not_found_reply(category_name)
    else:
        return "Hubo un problema eliminando la categoría. Intentá de nuevo."


async def _handle_list_categories(sender_phone: str) -> str:
    """Maneja la solicitud de listar categorías con totales."""
    from app.models.database import SessionLocal, Usuario

    session = SessionLocal()
    try:
        user = session.query(Usuario).filter(Usuario.whatsapp_id == sender_phone).first()
        if user is None:
            return "No encontré tu cuenta."
        user_id = user.id
    finally:
        session.close()

    result = FinanceService.get_categories_with_totals(user_id)
    if result.status == "ok":
        return _format_categories_list(result)
    else:
        return "Hubo un problema consultando las categorías."


async def _register_and_reply_with_hint(
    sender_phone: str,
    whatsapp_message_id: str | None,
    text_body: str,
    extracted_data: dict,
) -> str:
    """
    Registra el movimiento inmediatamente con la categoría inferida,
    guarda el último movimiento en Redis y devuelve el mensaje con hint.
    Soporta varios movimientos por mensaje (multiop).
    """
    movements = extracted_data.get("movements") or [extracted_data]

    # Confirmación de categoría SOLO con exactamente 1 movimiento con categoría inferida.
    if len(movements) == 1 and movements[0].get("category"):
        return await _register_single_with_hint(
            sender_phone, whatsapp_message_id, text_body, extracted_data, movements[0]
        )

    return await _register_multiop(
        sender_phone, whatsapp_message_id, text_body, extracted_data, movements
    )


async def _register_single_with_hint(
    sender_phone: str,
    whatsapp_message_id: str | None,
    text_body: str,
    extracted_data: dict,
    mov: dict,
) -> str:
    category_name = mov.get("category")
    llm_result = {**extracted_data, **mov}
    result = FinanceService.register_movement_with_category(
        sender_phone=sender_phone,
        whatsapp_message_id=whatsapp_message_id,
        original_text=text_body,
        movement_type=llm_result.get("movement_type", "egreso"),
        amount=Decimal(str(llm_result.get("amount") or 0)),
        currency=llm_result.get("currency", "ARS"),
        description=_movement_description(llm_result),
        category_name=category_name,
        create_category_if_missing=True,
        fecha_movimiento=resolve_relative_date(mov.get("fecha"), date.today()),  # noqa: DTZ011
    )

    print(
        "[MOVEMENT_REGISTRATION]",
        f"user={sender_phone}",
        f"message_id={whatsapp_message_id}",
        f"status={result.status}",
    )

    if result.status == "needs_category_confirmation":
        return _route_needs_category_confirmation(
            sender_phone, whatsapp_message_id, text_body, llm_result, category_name
        )

    if result.status != "registered":
        return _registration_dispatch_reply(result, llm_result)

    # Guardar el último movimiento en Redis para posible cambio de categoría
    last = LastRegisteredMovement(
        movement_id=result.movement_id,
        sender_phone=sender_phone,
        movement_type=llm_result.get("movement_type", "egreso"),
        amount=Decimal(str(llm_result.get("amount") or 0)),
        currency=llm_result.get("currency", "ARS"),
        description=_movement_description(llm_result),
        category_name=category_name,
    )
    await ConversationService.set_last_movement(sender_phone, last)

    movement_type = llm_result.get("movement_type") or "movimiento"
    description = _movement_description(llm_result)
    amount = _format_amount(llm_result.get("amount"))
    currency = str(llm_result.get("currency") or "ARS").upper()

    reply = f"✅ Registré tu {movement_type}: {description} por ${amount} {currency}."
    reply += f"\n📁 Categoría: {category_name}."
    reply += f"\n{_category_hint_reply()}"
    return reply


async def _route_needs_category_confirmation(
    sender_phone: str,
    whatsapp_message_id: str | None,
    text_body: str,
    extracted_data: dict,
    category_name: str | None,
) -> str:
    """Deriva una categoría no resuelta al flujo existente de confirmación."""
    pending = PendingMovement(
        sender_phone=sender_phone,
        whatsapp_message_id=whatsapp_message_id,
        original_text=text_body,
        movement_type=extracted_data.get("movement_type", "egreso"),
        amount=Decimal(str(extracted_data.get("amount") or 0)),
        currency=extracted_data.get("currency", "ARS"),
        description=_movement_description(extracted_data),
        inferred_category=category_name,
        llm_result_extra=extracted_data,
    )
    await ConversationService.set_pending_movement(sender_phone, pending)
    return _category_confirmation_reply(category_name or "")


async def _register_multiop(
    sender_phone: str,
    whatsapp_message_id: str | None,
    text_body: str,
    extracted_data: dict,
    movements: list,
) -> str:
    results = []
    for mov in movements:
        llm_result = {**extracted_data, **mov}
        result = FinanceService.register_movement_from_whatsapp_text(
            sender_phone=sender_phone,
            whatsapp_message_id=whatsapp_message_id,
            original_text=text_body,
            llm_result=llm_result,
            fecha_movimiento=resolve_relative_date(mov.get("fecha"), date.today()),  # noqa: DTZ011
        )
        print(
            "[MOVEMENT_REGISTRATION]",
            f"user={sender_phone}",
            f"message_id={whatsapp_message_id}",
            f"status={result.status}",
        )
        results.append(result)
    return _multiop_registration_reply(results, extracted_data, movements)


# ---------------------------------------------------------------------------
# STK-46: Helpers de límites de gasto por categoría
# ---------------------------------------------------------------------------


def _format_limit_amount(amount) -> str:
    """Formatea un monto con separador de miles '.' y decimales ',' (es-AR)."""
    try:
        decimal_amount = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return str(amount)

    if decimal_amount == decimal_amount.to_integral_value():
        decimal_amount = decimal_amount.quantize(Decimal("1"))
    else:
        decimal_amount = decimal_amount.quantize(Decimal("0.01"))

    formatted = f"{decimal_amount:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _current_year() -> int:
    from datetime import date

    return date.today().year


def _limit_month_label(month: int, year: int) -> str:
    return LimitService.month_label(month, year, _current_year())


def _limit_registered_reply(
    category_name: str,
    amount,
    month: int,
    year: int,
    *,
    edit: bool = False,
) -> str:
    label = _limit_month_label(month, year)
    amount_text = _format_limit_amount(amount)
    if edit:
        reply = (
            f"✅ Listo, se Registró tu límite para {label}. "
            f"📁 Categoría: {category_name}. 🎯 Límite a gastar: ${amount_text}."
        )
    else:
        reply = (
            f"✅ Registré tu límite para {label}. "
            f"📁 Categoría: {category_name}. 🎯 Límite a gastar: ${amount_text}."
        )
        reply += "\n¿No te convence algo? Indícame y lo cambiamos."
    return reply


def _year_confirmation_reply(month: int, year: int) -> str:
    name = LimitService.month_label(month, year, _current_year()).split()[0]
    return f"⏩ ¿Quieres crear un límite de gastos para {name} de {year}?"


def _limit_missing_reply(result) -> str:
    if result.status == "needs_category":
        return "¿A qué categoría querés aplicar el límite?"
    if result.status == "needs_amount":
        if result.category_name:
            return f"¿Cuál es el monto máximo del límite para {result.category_name}?"
        return "¿Cuál es el monto máximo del límite?"
    return "Necesito que me completes la categoría o el monto del límite."


def _limit_list_reply(result) -> str:
    limits = result.limits or []
    if not limits:
        return "No tenés límites de gasto definidos por ahora."
    lines = ["🎯 *Tus límites de gasto:*"]
    for entry in limits:
        amount = _format_limit_amount(entry.amount)
        label = _limit_month_label(entry.month, entry.year)
        lines.append(f"• {entry.category_name} — ${amount} — {label}")
    return "\n".join(lines)


def _limit_selection_reply(category_name: str, candidates: list[dict]) -> str:
    lines = [f"Tengo varios límites de {category_name}. ¿A cuál te referís?"]
    for candidate in candidates:
        label = _limit_month_label(candidate["month"], candidate["year"])
        amount = _format_limit_amount(candidate["amount"])
        lines.append(f"• {label} — ${amount}")
    return "\n".join(lines)


def _limit_delete_reply(result, category_name: str) -> str:
    if result.status == "deleted":
        label = _limit_month_label(result.month, result.year)
        return f"✅ Listo, eliminé el límite de {result.category_name or category_name} de {label}."
    if result.status == "not_found":
        return f"No encontré un límite de {category_name} para eliminar."
    if result.status == "needs_month_selection":
        return _limit_selection_reply(category_name, result.candidates)
    if result.status == "user_not_found":
        return "No encontré una cuenta vinculada a este WhatsApp."
    if result.status == "persistence_error":
        return "Hubo un problema eliminando el límite. Intentá nuevamente en unos minutos."
    return "No pude procesar la eliminación del límite."


_CANCEL_PATTERNS = re.compile(
    r'\b(?:cancel(?:ar|á|alo|ela)?|dej(?:a|á|alo|elo)?|olvid(?:a|á|alo|elo)?'
    r'|anul(?:a|á|alo|ela)?|no quiero|no me interesa|para nada)\b',
    re.IGNORECASE,
)

_MONTH_NAMES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def _is_cancel_request(text: str) -> bool:
    if not text:
        return False
    return _CANCEL_PATTERNS.search(text) is not None


_CONFIRM_PATTERNS = re.compile(
    r"\b(?:sí|si|dale|ok|okey|confirmo|confirmame|afirmativo|de acuerdo|claro|"
    r"genial|perfecto|listo|bárbaro|barbaro|bueno|yes)\b",
    re.IGNORECASE,
)


def _is_confirm_request(text: str) -> bool:
    """Detecta una respuesta afirmativa clara (sí/dale/ok) al confirmar un límite.

    Se usa como respaldo cundo el LLM clasifica el 'sí' como out_of_scope/greeting
    porque el mensaje suelto no trae contexto de la pregunta previa.
    """
    if not text:
        return False
    return _CONFIRM_PATTERNS.search(text) is not None


def _extract_amount_from_text(text: str) -> float | None:
    """Extrae un monto numérico del texto (con o sin separadores de miles)."""
    if not text:
        return None
    match = re.search(r'\d[\d.,]*', text)
    if not match:
        return None
    raw = match.group(0)
    # "1.234.567,89" / "1234,56" / "100000" -> número plano con decimal '.'
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    elif "." in raw:
        parts = raw.split(".")
        if len(parts) == 2 and len(parts[1]) == 2:
            raw = raw.replace(".", ".")
        else:
            raw = raw.replace(".", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _extract_category_from_text(text: str) -> str | None:
    """Usa el texto plano como categoría cuando el LLM no la detecta."""
    candidate = text.strip().strip("!?.")
    if not candidate or len(candidate) > 100:
        return None
    if _extract_amount_from_text(candidate) is not None:
        return None
    return candidate.lower()


def _extract_month_from_text(text: str) -> int | None:
    """Detecta el número de mes por su nombre dentro del texto."""
    if not text:
        return None
    lowered = text.lower()
    for name, month in _MONTH_NAMES.items():
        if name in lowered:
            return month
    return None


def _limit_base_data(pending: PendingLimit) -> dict:
    """Convierte un límite pendiente a dict de datos del LLM."""
    return {
        "limit_category": pending.category,
        "limit_amount": float(pending.amount) if pending.amount is not None else None,
        "limit_month": pending.month,
        "limit_year": pending.year,
    }


def _last_limit_from_pending(pending: PendingLimit) -> LastCreatedLimit | None:
    """Reconstruye el último límite creado desde un pending de edición."""
    if pending.limit_id is None:
        return None
    return LastCreatedLimit(
        limit_id=pending.limit_id,
        sender_phone=pending.sender_phone,
        category_name=pending.category,
        amount=pending.amount,
        month=pending.month,
        year=pending.year,
    )


async def _handle_create_limit(
    sender_phone: str,
    extracted_data: dict,
    last_limit: LastCreatedLimit | None = None,
    edit: bool | None = None,
) -> str:
    """Crea o edita un límite de gasto, orquestando los pasos multi-turno."""
    if edit is None:
        edit = last_limit is not None

    result = LimitService.create_limit(sender_phone, extracted_data, last_limit=last_limit)

    if result.status in ("created", "updated"):
        await ConversationService.set_last_limit(
            sender_phone,
            LastCreatedLimit(
                limit_id=result.limit_id,
                sender_phone=sender_phone,
                category_name=result.category_name,
                amount=result.amount,
                month=result.month,
                year=result.year,
            ),
        )
        await ConversationService.clear_state(sender_phone)
        return _limit_registered_reply(
            result.category_name,
            result.amount,
            result.month,
            result.year,
            edit=edit,
        )

    if result.status == "needs_year_confirmation":
        pending = PendingLimit(
            sender_phone=sender_phone,
            category=result.category_name,
            amount=result.amount,
            month=result.proposed_month,
            year=result.proposed_year,
            is_edit=edit,
            limit_id=last_limit.limit_id if last_limit is not None else None,
        )
        await ConversationService.set_pending_limit(
            sender_phone,
            pending,
            step="awaiting_limit_year_confirmation",
        )
        return _year_confirmation_reply(result.proposed_month, result.proposed_year)

    if result.status in ("needs_category", "needs_amount"):
        month = extracted_data.get("limit_month")
        year = extracted_data.get("limit_year")
        if month is None and last_limit is not None:
            month = last_limit.month
        if year is None and last_limit is not None:
            year = last_limit.year
        pending = PendingLimit(
            sender_phone=sender_phone,
            category=result.category_name,
            amount=result.amount,
            month=month,
            year=year,
            is_edit=edit,
            limit_id=last_limit.limit_id if last_limit is not None else None,
        )
        await ConversationService.set_pending_limit(
            sender_phone,
            pending,
            step="awaiting_limit_data",
        )
        return _limit_missing_reply(result)

    if result.status == "user_not_found":
        return "No encontré una cuenta vinculada a este WhatsApp."
    if result.status == "persistence_error":
        return "Hubo un problema guardando tu límite. Intentá nuevamente en unos minutos."
    return "No pude procesar tu solicitud de límite."


async def _handle_change_limit(sender_phone: str, extracted_data: dict) -> str:
    """Edita el último límite creado con los campos nuevos del usuario."""
    last_limit = await ConversationService.get_last_limit(sender_phone)
    if last_limit is None:
        return (
            "No tengo un límite reciente para cambiar. "
            "Podés crear uno así: 'poné un límite de 300000 para ropa'."
        )
    return await _handle_create_limit(sender_phone, extracted_data, last_limit=last_limit)


async def _handle_list_limits(sender_phone: str) -> str:
    from app.models.database import SessionLocal, Usuario

    session = SessionLocal()
    try:
        user = session.query(Usuario).filter(Usuario.whatsapp_id == sender_phone).first()
        if user is None:
            return "No encontré tu cuenta."
        result = LimitService.list_limits(user.id)
        return _limit_list_reply(result)
    except Exception as exc:
        print(f"[LIMIT_LIST] Error: {type(exc).__name__}: {exc}")
        return "Hubo un problema consultando tus límites."
    finally:
        session.close()


async def _handle_delete_limit(sender_phone: str, extracted_data: dict) -> str:
    category_name = extracted_data.get("limit_category")
    month = extracted_data.get("limit_month")
    year = extracted_data.get("limit_year")
    if not category_name:
        await ConversationService.set_pending_limit_delete_category(
            sender_phone,
            PendingLimitDelete(
                sender_phone=sender_phone,
                category_name=None,
                month=month,
                year=year,
            ),
        )
        return "¿Qué límite querés eliminar? Indicame la categoría."
    result = LimitService.delete_limit(sender_phone, category_name, month=month, year=year)
    if result.status == "needs_month_selection":
        await ConversationService.set_pending_limit_delete(
            sender_phone,
            PendingLimitDelete(
                sender_phone=sender_phone,
                category_name=result.category_name or category_name,
                candidates=result.candidates,
            ),
        )
    return _limit_delete_reply(result, category_name)


# ---------------------------------------------------------------------------
# Dispatch pipeline
# ---------------------------------------------------------------------------


async def process_incoming_message(
    sender_phone: str,
    text_body: str,
    whatsapp_message_id: str | None = None,
) -> DispatchResult:
    """
    Process an incoming text message through the full dispatch pipeline.

    This includes:
    1. Onboarding check
    2. /link command interception
    3. Multi-turn state checks (rename, reminder data)
    4. LLM processing
    5. Intent dispatch (financial movement, reminders, categories, etc.)

    Args:
        sender_phone: The sender's WhatsApp phone number.
        text_body: The raw text body of the message.
        whatsapp_message_id: Optional WhatsApp message ID for dedup.

    Returns:
        DispatchResult with reply_text and debug metadata.
    """
    onboarding_result = OnboardingService.prepare_whatsapp_message(sender_phone)
    if onboarding_result.decision == OnboardingDecision.SEND_INVITATION:
        return DispatchResult(
            reply_text=_onboarding_invitation_reply(
                onboarding_result.registration_url,
                onboarding_result.invitation_ttl_minutes,
            ),
            service_invoked="onboarding",
        )
    if onboarding_result.decision == OnboardingDecision.SUPPRESS_RESPONSE:
        return DispatchResult(reply_text="", service_invoked="onboarding")
    if onboarding_result.decision == OnboardingDecision.ERROR:
        return DispatchResult(
            reply_text="No pude verificar tu cuenta. Intentá nuevamente en unos minutos.",
            service_invoked="onboarding",
        )

    # ------------------------------------------------------------------
    # STK-89: comando exacto para pedir un enlace de acceso al dashboard.
    # ------------------------------------------------------------------
    if text_body.strip().lower() == "/link":
        dashboard_link_result = DashboardLinkService.generate_or_reuse(sender_phone)
        if dashboard_link_result.decision == DashboardLinkDecision.SEND_LINK:
            reply_text = _dashboard_link_reply(
                dashboard_link_result.login_url,
                dashboard_link_result.link_ttl_minutes,
            )
        elif dashboard_link_result.decision == DashboardLinkDecision.NOT_ELIGIBLE:
            reply_text = _DASHBOARD_LINK_NOT_ELIGIBLE_REPLY
        elif dashboard_link_result.decision == DashboardLinkDecision.ERROR:
            reply_text = "No pude generar tu enlace. Intentá nuevamente en unos minutos."
        else:  # SUPPRESS_RESPONSE
            reply_text = ""
        return DispatchResult(reply_text=reply_text, service_invoked="dashboard_link")

    # Track last message time for 24h window
    _update_ultimo_mensaje(sender_phone)

    # ----------------------------------------------------------
    # Multi-turn: renombrar recordatorio por título duplicado
    # ----------------------------------------------------------
    is_awaiting_rename = await ConversationService.is_awaiting_rename(sender_phone)

    if is_awaiting_rename:
        pending = await ConversationService.get_pending_rename(sender_phone)
        if pending is None:
            await ConversationService.clear_state(sender_phone)
            reply_text = "Se perdió el contexto. Podés volver a crear el recordatorio."
        else:
            new_concept = text_body.strip()
            if not new_concept:
                reply_text = "¿Qué nombre querés usar para el recordatorio?"
            else:
                llm_data = {
                    "reminder_concept": new_concept,
                    "reminder_day": pending.reminder_day,
                    "reminder_amount": float(pending.reminder_amount) if pending.reminder_amount else None,
                    "reminder_currency": pending.reminder_currency,
                }
                reminder_result = ReminderService.create_reminder(
                    sender_phone=sender_phone,
                    llm_result=llm_data,
                )
                if reminder_result.status != "duplicate_title":
                    await ConversationService.clear_state(sender_phone)
                reply_text = _reminder_creation_reply(reminder_result, llm_data)
        return DispatchResult(reply_text=reply_text, service_invoked="conversation")

    # ----------------------------------------------------------
    # Multi-turn: si estamos esperando datos de recordatorio
    # ----------------------------------------------------------
    is_awaiting_reminder = await ConversationService.is_awaiting_reminder_data(sender_phone)

    if is_awaiting_reminder:
        pending = await ConversationService.get_pending_reminder(sender_phone)
        if pending is None:
            await ConversationService.clear_state(sender_phone)
            reply_text = "Se perdió el contexto. Podés volver a crear el recordatorio."
        else:
            # Extraer día del texto usando LLM
            extracted_data = await LLMService.process_message(
                text_body, context=build_user_context(sender_phone)
            )
            new_day = extracted_data.get("reminder_day")
            # Fallback: extraer número del texto
            if new_day is None:
                import re
                match = re.search(r'\b(\d{1,2})\b', text_body)
                if match:
                    candidate = int(match.group(1))
                    if 1 <= candidate <= 31:
                        new_day = candidate

            if new_day is None:
                reply_text = "Necesito un día del mes (1 al 31). ¿Qué día vence?"
            else:
                llm_data = {
                    "reminder_concept": pending.reminder_concept,
                    "reminder_day": new_day,
                    "reminder_amount": float(pending.reminder_amount) if pending.reminder_amount else None,
                    "reminder_currency": pending.reminder_currency,
                }
                reminder_result = ReminderService.create_reminder(
                    sender_phone=sender_phone,
                    llm_result=llm_data,
                )
                await ConversationService.clear_state(sender_phone)
                reply_text = _reminder_creation_reply(reminder_result, llm_data)
        return DispatchResult(reply_text=reply_text, service_invoked="conversation")

    # ----------------------------------------------------------
    # Multi-turn STK-46: confirmar el año de un límite para un mes pasado
    # ----------------------------------------------------------
    is_awaiting_limit_year = await ConversationService.is_awaiting_limit_year_confirmation(sender_phone)

    if is_awaiting_limit_year:
        pending = await ConversationService.get_pending_limit(sender_phone)
        if pending is None:
            await ConversationService.clear_state(sender_phone)
            return DispatchResult(
                reply_text="Se perdió el contexto. Podés volver a crear el límite.",
                service_invoked="conversation",
            )
        extracted_data = await LLMService.process_message(
            text_body, context=build_user_context(sender_phone)
        )
        intent = extracted_data.get("intent", "out_of_scope")
        if intent == "reject_limit" or _is_cancel_request(text_body):
            await ConversationService.clear_state(sender_phone)
            return DispatchResult(
                reply_text="Listo, no creé ningún límite de gasto.",
                service_invoked="conversation",
            )
        if intent == "confirm_limit" or (
            intent in ("out_of_scope", "greeting") and _is_confirm_request(text_body)
        ):
            reply_text = await _handle_create_limit(
                sender_phone,
                _limit_base_data(pending),
                last_limit=_last_limit_from_pending(pending),
                edit=pending.is_edit,
            )
            return DispatchResult(reply_text=reply_text, service_invoked="conversation")
        # El mensaje no responde la confirmación de año (saludo, gasto, otro tema):
        # el flujo del límite quedó abandonado. Limpiar el estado para que no
        # secuestre los mensajes siguientes y procesar normalmente (fall-through).
        await ConversationService.clear_state(sender_phone)

    # ----------------------------------------------------------
    # Multi-turn STK-46: completar categoría y/o monto del límite
    # ----------------------------------------------------------
    is_awaiting_limit_data = await ConversationService.is_awaiting_limit_data(sender_phone)

    if is_awaiting_limit_data:
        pending = await ConversationService.get_pending_limit(sender_phone)
        if pending is None:
            await ConversationService.clear_state(sender_phone)
            reply_text = "Se perdió el contexto. Podés volver a crear el límite."
        else:
            extracted_data = await LLMService.process_message(
                text_body, context=build_user_context(sender_phone)
            )
            intent = extracted_data.get("intent", "out_of_scope")

            if intent == "reject_limit" or _is_cancel_request(text_body):
                await ConversationService.clear_state(sender_phone)
                reply_text = "Listo, cancelé la configuración del límite de gasto."
            else:
                base = _limit_base_data(pending)
                if base["limit_category"] is None:
                    base["limit_category"] = (
                        extracted_data.get("limit_category")
                        or _extract_category_from_text(text_body)
                    )
                if base["limit_amount"] is None:
                    base["limit_amount"] = (
                        extracted_data.get("limit_amount")
                        or _extract_amount_from_text(text_body)
                    )
                if extracted_data.get("limit_month") is not None:
                    base["limit_month"] = extracted_data.get("limit_month")
                if extracted_data.get("limit_year") is not None:
                    base["limit_year"] = extracted_data.get("limit_year")
                reply_text = await _handle_create_limit(
                    sender_phone,
                    base,
                    last_limit=_last_limit_from_pending(pending),
                    edit=pending.is_edit,
                )
        return DispatchResult(reply_text=reply_text, service_invoked="conversation")

    # ----------------------------------------------------------
    # Multi-turn STK-46: el usuario debe indicar la categoría a eliminar
    # ----------------------------------------------------------
    is_awaiting_delete_category = await ConversationService.is_awaiting_limit_delete_category(sender_phone)

    if is_awaiting_delete_category:
        pending_delete = await ConversationService.get_pending_limit_delete(sender_phone)
        if pending_delete is None:
            await ConversationService.clear_state(sender_phone)
            reply_text = "Se perdió el contexto de la eliminación. Volvé a indicarme qué límite querés eliminar."
        else:
            extracted_data = await LLMService.process_message(
                text_body, context=build_user_context(sender_phone)
            )
            category_name = extracted_data.get("limit_category") or _extract_category_from_text(text_body)
            if not category_name:
                reply_text = "¿Qué límite querés eliminar? Indicame la categoría."
            else:
                result = LimitService.delete_limit(
                    sender_phone,
                    category_name,
                    month=pending_delete.month,
                    year=pending_delete.year,
                )
                if result.status == "needs_month_selection":
                    await ConversationService.set_pending_limit_delete(
                        sender_phone,
                        PendingLimitDelete(
                            sender_phone=sender_phone,
                            category_name=result.category_name or category_name,
                            candidates=result.candidates,
                        ),
                    )
                else:
                    await ConversationService.clear_state(sender_phone)
                reply_text = _limit_delete_reply(result, category_name)
        return DispatchResult(reply_text=reply_text, service_invoked="conversation")

    # ----------------------------------------------------------
    # Multi-turn STK-46: elegir el mes del límite a eliminar
    # ----------------------------------------------------------
    is_awaiting_limit_month = await ConversationService.is_awaiting_limit_month_selection(sender_phone)

    if is_awaiting_limit_month:
        pending_delete = await ConversationService.get_pending_limit_delete(sender_phone)
        if pending_delete is None:
            await ConversationService.clear_state(sender_phone)
            reply_text = "Se perdió el contexto de la eliminación. Volvé a indicarme qué límite querés eliminar."
        else:
            extracted_data = await LLMService.process_message(
                text_body, context=build_user_context(sender_phone)
            )
            month = extracted_data.get("limit_month")
            if month is None:
                month = _extract_month_from_text(text_body)
            if month is None:
                reply_text = _limit_selection_reply(
                    pending_delete.category_name,
                    pending_delete.candidates,
                )
            else:
                result = LimitService.delete_limit(
                    sender_phone,
                    pending_delete.category_name,
                    month=month,
                    year=extracted_data.get("limit_year"),
                )
                await ConversationService.clear_state(sender_phone)
                reply_text = _limit_delete_reply(result, pending_delete.category_name)
        return DispatchResult(reply_text=reply_text, service_invoked="conversation")

    # Procesar mensaje con LLM (fecha + categorías del usuario como contexto)
    extracted_data = await LLMService.process_message(
        text_body, context=build_user_context(sender_phone)
    )
    intent = extracted_data.get("intent", "out_of_scope")

    # ----------------------------------------------------------
    # STK-39 v2: Manejar intents
    # ----------------------------------------------------------
    if intent == "create_limit":
        reply_text = await _handle_create_limit(sender_phone, extracted_data)
        service_invoked = "limit"

    elif intent == "change_limit":
        reply_text = await _handle_change_limit(sender_phone, extracted_data)
        service_invoked = "limit"

    elif intent == "list_limits":
        reply_text = await _handle_list_limits(sender_phone)
        service_invoked = "limit"

    elif intent == "delete_limit":
        reply_text = await _handle_delete_limit(sender_phone, extracted_data)
        service_invoked = "limit"

    elif intent == "change_category":
        reply_text = await _handle_change_category(sender_phone, extracted_data)
        service_invoked = "finance"

    elif intent == "delete_category":
        reply_text = await _handle_delete_category(sender_phone, extracted_data)
        service_invoked = "finance"

    elif intent == "list_categories":
        reply_text = await _handle_list_categories(sender_phone)
        service_invoked = "finance"

    elif intent == "list_reminders":
        reply_text = await _handle_list_reminders(sender_phone)
        service_invoked = "reminder"

    elif intent == "update_reminder":
        reminder_concept = extracted_data.get("reminder_concept")
        reminder_id = extracted_data.get("reminder_id") or ""
        if reminder_concept:
            try:
                found = ReminderService.find_by_title(sender_phone, reminder_concept)
                if found:
                    reminder_id = str(found[0].id or "")
            except Exception:
                pass
        reminder_result = ReminderService.update_reminder(
            sender_phone=sender_phone,
            reminder_id=reminder_id,
            llm_result=extracted_data,
        )
        reply_text = _reminder_update_reply(reminder_result)
        service_invoked = "reminder"

    elif intent == "pause_reminder":
        concept = extracted_data.get("reminder_concept")
        if concept:
            reminder_result = ReminderService.pause_by_title(
                sender_phone=sender_phone,
                title=concept,
            )
        else:
            reminder_result = ReminderService.pause_reminder(
                sender_phone=sender_phone,
                reminder_id=extracted_data.get("reminder_id") or "",
            )
        reply_text = _reminder_state_reply(reminder_result, "paused")
        service_invoked = "reminder"

    elif intent == "activate_reminder":
        concept = extracted_data.get("reminder_concept")
        if concept:
            reminder_result = ReminderService.activate_by_title(
                sender_phone=sender_phone,
                title=concept,
            )
        else:
            reminder_result = ReminderService.activate_reminder(
                sender_phone=sender_phone,
                reminder_id=extracted_data.get("reminder_id") or "",
            )
        reply_text = _reminder_state_reply(reminder_result, "activated")
        service_invoked = "reminder"

    elif intent == "delete_reminder":
        concept = extracted_data.get("reminder_concept")
        if concept:
            reminder_result = ReminderService.delete_by_title(
                sender_phone=sender_phone,
                title=concept,
            )
        else:
            reminder_result = ReminderService.delete_reminder(
                sender_phone=sender_phone,
                reminder_id=extracted_data.get("reminder_id") or "",
            )
        reply_text = _reminder_delete_reply(reminder_result)
        service_invoked = "reminder"

    elif _is_financial_movement(extracted_data):
        # Nuevo movimiento: registrar inmediatamente con hint
        reply_text = await _register_and_reply_with_hint(
            sender_phone=sender_phone,
            whatsapp_message_id=whatsapp_message_id,
            text_body=text_body,
            extracted_data=extracted_data,
        )
        service_invoked = "finance"

    elif _is_create_reminder(extracted_data):
        validated_concept = _validate_reminder_concept(
            extracted_data.get("reminder_concept"), text_body
        )
        if validated_concept is None:
            reply_text = "¿Qué nombre querés ponerle al recordatorio?"
        elif not extracted_data.get("reminder_day"):
            pending_r = PendingReminder(
                sender_phone=sender_phone,
                reminder_concept=validated_concept,
                reminder_day=None,
                reminder_amount=(
                    Decimal(str(extracted_data["reminder_amount"]))
                    if extracted_data.get("reminder_amount") else None
                ),
                reminder_currency=extracted_data.get("reminder_currency") or "ARS",
            )
            await ConversationService.set_pending_reminder(sender_phone, pending_r)
            display_concept = validated_concept or "ese pago"
            reply_text = f"¿Qué día del mes querés que te avise de {display_concept}?"
        else:
            extracted_data["reminder_concept"] = validated_concept
            reminder_result = ReminderService.create_reminder(
                sender_phone=sender_phone,
                llm_result=extracted_data,
            )
            if reminder_result.status == "duplicate_title":
                pending_r = PendingReminder(
                    sender_phone=sender_phone,
                    reminder_concept=None,
                    reminder_day=extracted_data.get("reminder_day"),
                    reminder_amount=(
                        Decimal(str(extracted_data["reminder_amount"]))
                        if extracted_data.get("reminder_amount") else None
                    ),
                    reminder_currency=extracted_data.get("reminder_currency") or "ARS",
                )
                await ConversationService.set_pending_rename(sender_phone, pending_r)
            print(
                "[REMINDER_CREATION]",
                f"user={sender_phone}",
                f"status={reminder_result.status}",
            )
            reply_text = _reminder_creation_reply(reminder_result, extracted_data)
        service_invoked = "reminder"

    elif intent in ("greeting", "out_of_scope", "reminder", "budget_query", "expense_summary"):
        print(f"[{intent.upper()}] User {sender_phone}: {text_body}")
        reply_text = _safe_non_stk35_reply(extracted_data)
        service_invoked = "llm"

    else:
        # No hay conversación pendiente, procesar normalmente
        extracted_data = await LLMService.process_message(
            text_body, context=build_user_context(sender_phone)
        )
        intent = extracted_data.get("intent", "out_of_scope")

        # ----------------------------------------------------------
        # STK-39: Manejar intents de gestión de categorías
        # ----------------------------------------------------------
        if intent == "delete_category":
            reply_text = await _handle_delete_category(sender_phone, extracted_data)
            service_invoked = "finance"
        elif intent == "list_categories":
            reply_text = await _handle_list_categories(sender_phone)
            service_invoked = "finance"
        elif _is_financial_movement(extracted_data):
            # Movimiento financiero: ver si tiene categoría inferida
            category_name = extracted_data.get("category")

            if category_name:
                # Guardar movimiento como pendiente para confirmar categoría
                pending = PendingMovement(
                    sender_phone=sender_phone,
                    whatsapp_message_id=whatsapp_message_id,
                    original_text=text_body,
                    movement_type=extracted_data.get("movement_type", "egreso"),
                    amount=Decimal(str(extracted_data.get("amount") or 0)),
                    currency=extracted_data.get("currency", "ARS"),
                    description=_movement_description(extracted_data),
                    inferred_category=category_name,
                    llm_result_extra=extracted_data,
                )
                await ConversationService.set_pending_movement(
                    sender_phone, pending
                )
                reply_text = _category_confirmation_reply(category_name)
                service_invoked = "conversation"
            else:
                # Sin categoría inferida, registrar directamente
                registration_result = FinanceService.register_movement_from_whatsapp_text(
                    sender_phone=sender_phone,
                    whatsapp_message_id=whatsapp_message_id,
                    original_text=text_body,
                    llm_result=extracted_data,
                    fecha_movimiento=resolve_relative_date(
                        extracted_data.get("fecha"), date.today()  # noqa: DTZ011
                    ),
                )
                print(
                    "[MOVEMENT_REGISTRATION]",
                    f"user={sender_phone}",
                    f"message_id={whatsapp_message_id}",
                    f"status={registration_result.status}",
                )
                if registration_result.status == "needs_category_confirmation":
                    reply_text = _route_needs_category_confirmation(
                        sender_phone,
                        whatsapp_message_id,
                        text_body,
                        extracted_data,
                        registration_result.category_name,
                    )
                    service_invoked = "conversation"
                else:
                    reply_text = _registration_dispatch_reply(registration_result, extracted_data)
                    service_invoked = "finance"
        elif intent in ("confirm_category", "reject_category"):
            # Estos intents no deberían llegar acá sin pending, pero por si acaso
            reply_text = "No encontré un movimiento pendiente para confirmar."
            service_invoked = "conversation"
        else:
            intent_str = extracted_data.get("intent", "out_of_scope")
            print(f"[{str(intent_str).upper()}] User {sender_phone}: {text_body}")
            reply_text = _safe_non_stk35_reply(extracted_data)
            service_invoked = "llm"

    return DispatchResult(
        reply_text=reply_text,
        raw_llm_response=extracted_data,
        service_invoked=service_invoked,
        intent=intent,
    )
