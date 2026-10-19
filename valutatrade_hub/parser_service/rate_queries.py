import re
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage


@dataclass(frozen=True, slots=True)
class RateQuote:
    """Котировка для отображения в пользовательском интерфейсе."""

    pair: str
    rate: float
    source: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RateListing:
    """Результат запроса курсов без зависимости от форматирования CLI."""

    quotes: tuple[RateQuote, ...]
    last_refresh: str
    message: str | None = None


def _fresh_quotes() -> tuple[dict[str, tuple[float, datetime, str]], str]:
    """Возвращает свежие котировки относительно USD из локального кеша."""
    cache = RatesStorage().load_cache()
    pairs = cache.get("pairs", {})

    if not pairs:
        return {}, ""

    ttl = SettingsLoader().get("rates_ttl_seconds", 300)
    if (
        isinstance(ttl, bool)
        or not isinstance(ttl, (int, float))
        or not isfinite(ttl)
        or ttl < 0
    ):
        raise ValueError("TTL курсов должен быть конечным неотрицательным числом")

    now = datetime.now(UTC)
    fresh: dict[str, tuple[float, datetime, str]] = {}

    for pair, entry in pairs.items():
        if not isinstance(pair, str) or not re.fullmatch(r"[A-Z]{2,5}_USD", pair):
            continue
        if not isinstance(entry, dict):
            continue

        rate = entry.get("rate")
        timestamp = entry.get("updated_at")
        source = entry.get("source", "неизвестен")
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not isinstance(timestamp, str)
            or not isinstance(source, str)
        ):
            continue

        try:
            rate = float(rate)
            updated_at = datetime.fromisoformat(timestamp)
        except (OverflowError, ValueError):
            continue

        if not isfinite(rate) or rate <= 0 or updated_at.utcoffset() is None:
            continue

        updated_at = updated_at.astimezone(UTC)
        age = (now - updated_at).total_seconds()
        if 0 <= age < ttl:
            fresh[pair.split("_")[0]] = (rate, updated_at, source)

    last_refresh = cache.get("last_refresh")
    return fresh, last_refresh if isinstance(last_refresh, str) else ""


def query_rates(
    currency: str | None = None,
    top: int | None = None,
    base: str = "USD",
) -> RateListing:
    """Проверяет фильтры и рассчитывает курсы для отображения."""
    if top is not None and top <= 0:
        raise ValueError("Значение --top должно быть положительным")

    base_code = base.strip().upper()
    if not re.fullmatch(r"[A-Z]{2,5}", base_code):
        raise ValueError("Некорректная базовая валюта")

    currency_code = currency.strip().upper() if currency is not None else None
    if currency_code is not None and not re.fullmatch(r"[A-Z]{2,5}", currency_code):
        raise ValueError("Некорректный код валюты")

    quotes, last_refresh = _fresh_quotes()
    if not quotes:
        return RateListing(
            (),
            "",
            "Локальный кеш курсов пуст или устарел. Выполните 'update-rates'.",
        )

    if base_code == "USD":
        base_price = 1.0
        base_time = datetime.now(UTC)
    else:
        if base_code not in quotes:
            raise ApiRequestError(
                f"Курс {base_code}_USD отсутствует или устарел. Выполните update-rates."
            )
        base_price, base_time, _ = quotes[base_code]

    codes = sorted(quotes)
    if currency_code is not None:
        if currency_code not in quotes:
            return RateListing(
                (),
                last_refresh,
                f"Курс для '{currency_code}' не найден в актуальном кеше.",
            )
        codes = [currency_code]

    if top is not None:
        crypto_codes = set(ParserConfig().crypto_currencies)
        codes = [code for code in codes if code in crypto_codes]
        codes.sort(key=lambda code: (-quotes[code][0], code))
        codes = codes[:top]
        if not codes:
            return RateListing(
                (),
                last_refresh,
                "В кеше нет актуальных курсов криптовалют. Выполните 'update-rates'.",
            )

    rows = []
    for code in codes:
        usd_price, updated_at, source = quotes[code]
        rate = usd_price / base_price
        if not isfinite(rate) or rate <= 0:
            continue
        rows.append(
            RateQuote(
                pair=f"{code}_{base_code}",
                rate=rate,
                source=source,
                updated_at=min(updated_at, base_time),
            )
        )

    if not rows:
        raise ApiRequestError("Не удалось рассчитать курсы. Выполните update-rates.")

    return RateListing(tuple(rows), last_refresh)
