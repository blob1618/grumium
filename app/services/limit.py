import calendar
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from app.models.database import Categoria, LimiteCategoria, SessionLocal, Usuario
from app.services.finance import FinanceService

ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

_MESES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


@dataclass
class LimitResult:
    """Resultado de una operación sobre límites de gasto por categoría."""
    status: str
    message: str
    limit_id: str | None = None
    category_name: str | None = None
    amount: Decimal | None = None
    month: int | None = None
    year: int | None = None
    proposed_month: int | None = None
    proposed_year: int | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class LimitEntry:
    category_name: str
    amount: Decimal
    month: int
    year: int


@dataclass
class LimitListResult:
    status: str
    message: str
    limits: list[LimitEntry] = field(default_factory=list)


class LimitService:
    @staticmethod
    def _normalize_text(value: Any, max_length: int = 200) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return text[:max_length]

    @staticmethod
    def _normalize_amount(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        if not amount.is_finite() or amount <= 0:
            return None
        return amount

    @staticmethod
    def _normalize_month(value: Any) -> int | None:
        if value is None:
            return None
        try:
            month = int(value)
        except (TypeError, ValueError):
            return None
        if month < 1 or month > 12:
            return None
        return month

    @staticmethod
    def _normalize_year(value: Any) -> int | None:
        if value is None:
            return None
        try:
            year = int(value)
        except (TypeError, ValueError):
            return None
        return year

    @classmethod
    def _result(
        cls,
        status: str,
        message: str,
        limit_id: str | None = None,
        category_name: str | None = None,
        amount: Decimal | None = None,
        month: int | None = None,
        year: int | None = None,
        proposed_month: int | None = None,
        proposed_year: int | None = None,
        candidates: list[dict[str, Any]] | None = None,
    ) -> LimitResult:
        return LimitResult(
            status=status,
            message=message,
            limit_id=limit_id,
            category_name=category_name,
            amount=amount,
            month=month,
            year=year,
            proposed_month=proposed_month,
            proposed_year=proposed_year,
            candidates=candidates or [],
        )

    @staticmethod
    def _get_user(session, sender_phone: str) -> Usuario | None:
        return (
            session.query(Usuario)
            .filter(Usuario.whatsapp_id == sender_phone)
            .first()
        )

    @staticmethod
    def _uuid(value: Any) -> UUID | None:
        try:
            return UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            return None

    @classmethod
    def month_label(cls, month: int, year: int, current_year: int) -> str:
        name = _MESES[month] if 1 <= month <= 12 else ""
        if year != current_year:
            return f"{name} {year}"
        return name

    @classmethod
    def _resolve_period(
        cls,
        month: int | None,
        year: int | None,
        today: date,
    ) -> tuple[int, int, bool]:
        """Resuelve (year, month, needs_year_confirmation).

        - Con año explícito, se usa tal cual.
        - Sin mes, se usa el mes actual.
        - Con mes pero sin año: si el mes ya pasó en el año actual,
          propone el año siguiente (needs_year_confirmation=True).
        """
        if year is not None and month is not None:
            return year, month, False

        if month is None:
            return today.year, today.month, False

        if (today.year, month) < (today.year, today.month):
            return today.year + 1, month, True
        return today.year, month, False

    # ------------------------------------------------------------------
    # Creación / edición (upsert por categoría + período)
    # ------------------------------------------------------------------

    @classmethod
    def create_limit(
        cls,
        sender_phone: str,
        data: dict,
        last_limit=None,
        today: date | None = None,
    ) -> LimitResult:
        """Crea o actualiza (upsert) el límite mensual de una categoría.

        `last_limit` aporta el contexto del último límite creado cuando la
        solicitud es una edición (intent change_limit).
        """
        today = today or datetime.now(ARGENTINA_TZ).date()
        sender = cls._normalize_text(sender_phone)
        if not sender:
            return cls._result("invalid_data", "sender_phone is required")
        if not isinstance(data, dict):
            return cls._result("invalid_data", "data must be a dict")

        category = cls._normalize_text(data.get("limit_category"))
        if category is None and last_limit is not None:
            category = cls._normalize_text(last_limit.category_name)

        amount = cls._normalize_amount(data.get("limit_amount"))
        if amount is None and last_limit is not None:
            amount = cls._normalize_amount(last_limit.amount)

        raw_month = data.get("limit_month")
        month = cls._normalize_month(raw_month) if raw_month is not None else None
        if month is None and last_limit is not None:
            month = cls._normalize_month(last_limit.month)

        raw_year = data.get("limit_year")
        year = cls._normalize_year(raw_year) if raw_year is not None else None
        if year is None and last_limit is not None:
            year = cls._normalize_year(last_limit.year)

        if amount is None:
            return cls._result(
                "needs_amount",
                "amount is required",
                category_name=category,
            )
        if category is None:
            return cls._result(
                "needs_category",
                "category is required",
                amount=amount,
                month=month,
                year=year,
            )

        resolved_year, resolved_month, needs_confirmation = cls._resolve_period(
            month, year, today
        )
        if needs_confirmation:
            return cls._result(
                "needs_year_confirmation",
                "month already passed",
                category_name=category,
                amount=amount,
                proposed_month=resolved_month,
                proposed_year=resolved_year,
            )

        session = SessionLocal()
        try:
            user = cls._get_user(session, sender)
            if user is None:
                return cls._result("user_not_found", "user not found")

            cat_result = FinanceService.create_category(user.id, category)
            if cat_result.status == "error":
                return cls._result(
                    "persistence_error",
                    "could not resolve category",
                )

            categoria_id = cls._uuid(cat_result.category_id)
            if categoria_id is None:
                return cls._result(
                    "persistence_error",
                    "could not resolve category",
                )

            category_name = cat_result.category_name or category
            inicio = date(resolved_year, resolved_month, 1)
            fin = date(
                resolved_year,
                resolved_month,
                calendar.monthrange(resolved_year, resolved_month)[1],
            )

            existing = (
                session.query(LimiteCategoria)
                .filter(
                    LimiteCategoria.usuario_id == user.id,
                    LimiteCategoria.categoria_id == categoria_id,
                    LimiteCategoria.inicio_periodo == inicio,
                )
                .first()
            )

            if existing is not None:
                existing.cantidad_max = amount
                existing.fin_periodo = fin
                session.commit()
                return cls._result(
                    "updated",
                    "limit updated",
                    limit_id=str(existing.id),
                    category_name=category_name,
                    amount=amount,
                    month=resolved_month,
                    year=resolved_year,
                )

            limite = LimiteCategoria(
                usuario_id=user.id,
                categoria_id=categoria_id,
                cantidad_max=amount,
                inicio_periodo=inicio,
                fin_periodo=fin,
            )
            session.add(limite)
            session.commit()
            return cls._result(
                "created",
                "limit created",
                limit_id=str(limite.id),
                category_name=category_name,
                amount=amount,
                month=resolved_month,
                year=resolved_year,
            )

        except SQLAlchemyError as exc:
            session.rollback()
            print(
                "[LIMIT_CREATION] Persistence error: "
                f"{type(exc).__name__}: {exc}"
            )
            return cls._result("persistence_error", "could not persist limit")

        except Exception as exc:
            session.rollback()
            print(
                "[LIMIT_CREATION] Error: "
                f"{type(exc).__name__}: {exc}"
            )
            return cls._result("persistence_error", "could not persist limit")

        finally:
            session.close()

    # ------------------------------------------------------------------
    # Listado (solo límites vigentes; los vencidos se filtran)
    # ------------------------------------------------------------------

    @classmethod
    def list_limits(
        cls,
        user_id,
        today: date | None = None,
    ) -> LimitListResult:
        today = today or datetime.now(ARGENTINA_TZ).date()
        session = SessionLocal()
        try:
            rows = (
                session.query(LimiteCategoria, Categoria)
                .join(Categoria, LimiteCategoria.categoria_id == Categoria.id)
                .filter(
                    LimiteCategoria.usuario_id == user_id,
                    LimiteCategoria.fin_periodo >= today,
                )
                .order_by(LimiteCategoria.inicio_periodo.asc())
                .all()
            )
            entries = [
                LimitEntry(
                    category_name=categoria.nombre,
                    amount=limite.cantidad_max,
                    month=limite.inicio_periodo.month,
                    year=limite.inicio_periodo.year,
                )
                for limite, categoria in rows
            ]
            return LimitListResult(
                status="ok",
                message="limits listed",
                limits=entries,
            )
        except Exception as exc:
            print(f"[LIMIT_LIST] Error: {type(exc).__name__}: {exc}")
            return LimitListResult(status="error", message="could not list limits")
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Eliminación
    # ------------------------------------------------------------------

    @classmethod
    def delete_limit(
        cls,
        sender_phone: str,
        category: str,
        month: int | None = None,
        year: int | None = None,
        today: date | None = None,
    ) -> LimitResult:
        """Elimina un límite vigente por categoría.

        Sin mes: si hay un único límite vigente lo borra; si hay varios,
        devuelve needs_month_selection con los candidatos (mes + valor).
        """
        today = today or datetime.now(ARGENTINA_TZ).date()
        sender = cls._normalize_text(sender_phone)
        category = cls._normalize_text(category)
        if not sender:
            return cls._result("invalid_data", "sender_phone is required")
        if not category:
            return cls._result("invalid_data", "category is required")

        month = cls._normalize_month(month)
        year = cls._normalize_year(year)

        session = SessionLocal()
        try:
            user = cls._get_user(session, sender)
            if user is None:
                return cls._result("user_not_found", "user not found")

            categoria = FinanceService._find_category(session, user.id, category)
            if categoria is None:
                return cls._result("not_found", "category has no limits")

            limits = (
                session.query(LimiteCategoria)
                .filter(
                    LimiteCategoria.usuario_id == user.id,
                    LimiteCategoria.categoria_id == categoria.id,
                    LimiteCategoria.fin_periodo >= today,
                )
                .all()
            )
            if not limits:
                return cls._result("not_found", "category has no limits")

            if month is None:
                if len(limits) == 1:
                    target = limits[0]
                else:
                    candidates = [
                        {
                            "limit_id": str(lim.id),
                            "month": lim.inicio_periodo.month,
                            "year": lim.inicio_periodo.year,
                            "amount": lim.cantidad_max,
                        }
                        for lim in limits
                    ]
                    return cls._result(
                        "needs_month_selection",
                        "select the month",
                        category_name=categoria.nombre,
                        candidates=candidates,
                    )
            else:
                month_matches = [
                    lim for lim in limits if lim.inicio_periodo.month == month
                ]
                if not month_matches:
                    return cls._result(
                        "not_found",
                        "no limit for that month",
                        category_name=categoria.nombre,
                    )
                if year is not None:
                    year_matches = [
                        lim for lim in month_matches if lim.inicio_periodo.year == year
                    ]
                    if year_matches:
                        month_matches = year_matches
                target = min(month_matches, key=lambda lim: lim.inicio_periodo)

            session.delete(target)
            session.commit()
            return cls._result(
                "deleted",
                "limit deleted",
                limit_id=str(target.id),
                category_name=categoria.nombre,
                amount=target.cantidad_max,
                month=target.inicio_periodo.month,
                year=target.inicio_periodo.year,
            )

        except Exception as exc:
            session.rollback()
            print(
                "[LIMIT_DELETE] Error: "
                f"{type(exc).__name__}: {exc}"
            )
            return cls._result("persistence_error", "could not delete limit")

        finally:
            session.close()
