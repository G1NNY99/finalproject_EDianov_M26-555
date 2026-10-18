from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from inspect import signature
from time import perf_counter
from typing import Any, ParamSpec, TypeVar

from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import get_action_logger

P = ParamSpec("P")
R = TypeVar("R")
_ACTION_CONTEXT: ContextVar[dict[str, float | str] | None] = ContextVar(
    "valutatrade_action_context", default=None
)


def set_action_context(
    *,
    rate: float | None = None,
    base: str | None = None,
    balance_before: float | None = None,
    balance_after: float | None = None,
) -> None:
    """Передаёт фактические значения операции в её журнал."""
    context = _ACTION_CONTEXT.get()
    if context is None:
        return

    if rate is not None:
        context["rate"] = rate
    if base is not None:
        context["base"] = base
    if balance_before is not None:
        context["balance_before"] = balance_before
    if balance_after is not None:
        context["balance_after"] = balance_after


def log_action(
    action: str,
    *,
    verbose: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Записывает результат операции и пробрасывает исходные исключения."""
    if not isinstance(action, str) or not action.strip():
        raise ValueError("Название операции не может быть пустым")

    action_name = action.strip().upper()

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        function_signature = signature(func)

        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            bound = function_signature.bind_partial(*args, **kwargs)
            parameters = bound.arguments
            started = perf_counter()
            token = _ACTION_CONTEXT.set({})
            result: Any = None
            error: Exception | None = None

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as exc:
                error = exc
                raise
            finally:
                try:
                    context = _ACTION_CONTEXT.get() or {}
                    result_data = result if isinstance(result, dict) else {}

                    user_value = parameters.get(
                        "username",
                        parameters.get("user_id", parameters.get("user", "-")),
                    )
                    user = getattr(user_value, "username", user_value)
                    if user is None:
                        user = "-"

                    currency = parameters.get(
                        "currency_code", parameters.get("currency", "-")
                    )
                    amount = parameters.get("amount", "-")

                    rate = context.get(
                        "rate", result_data.get("rate", parameters.get("rate"))
                    )
                    base = context.get(
                        "base",
                        result_data.get(
                            "base",
                            parameters.get("base", parameters.get("base_currency")),
                        ),
                    )
                    if base is None and action_name in {"BUY", "SELL"}:
                        base = SettingsLoader().get("base_currency", "USD")

                    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
                    fields = [
                        timestamp,
                        action_name,
                        f"user={user!r}",
                        f"currency={currency!r}",
                        f"amount={amount}",
                    ]

                    if rate is not None:
                        fields.append(f"rate={rate}")
                    if base is not None:
                        fields.append(f"base={base!r}")

                    if error is None:
                        fields.append("result=OK")
                    else:
                        fields.append("result=ERROR")
                        fields.append(f"error_type={type(error).__name__}")
                        fields.append(f"error_message={str(error)!r}")

                    if verbose:
                        duration_ms = (perf_counter() - started) * 1000
                        fields.append(f"function={func.__name__!r}")
                        fields.append(f"duration_ms={duration_ms:.2f}")

                        for key in ("balance_before", "balance_after"):
                            value = context.get(key, result_data.get(key))
                            if value is not None:
                                fields.append(f"{key}={value!r}")

                    get_action_logger().info(" ".join(fields))
                finally:
                    _ACTION_CONTEXT.reset(token)

        return wrapper

    return decorator
