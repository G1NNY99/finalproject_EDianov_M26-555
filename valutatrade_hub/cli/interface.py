import argparse
import re
import shlex
from datetime import UTC, datetime
from math import isfinite

from prettytable import PrettyTable

from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
)
from valutatrade_hub.core.models import User
from valutatrade_hub.core.usecases import (
    buy,
    get_rate,
    login,
    register,
    sell,
    show_portfolio,
)
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater


def create_parser() -> argparse.ArgumentParser:
    """Создаёт парсер команд торговой платформы и сервиса курсов."""
    parser = argparse.ArgumentParser(prog="valutatrade-hub")
    commands = parser.add_subparsers(dest="command", required=True)

    register_parser = commands.add_parser("register")
    register_parser.add_argument("--username", required=True)
    register_parser.add_argument("--password", required=True)

    login_parser = commands.add_parser("login")
    login_parser.add_argument("--username", required=True)
    login_parser.add_argument("--password", required=True)

    portfolio_parser = commands.add_parser("show-portfolio")
    portfolio_parser.add_argument("--base", default="USD")

    buy_parser = commands.add_parser(
        "buy",
        description="Покупка валюты за USD.",
        epilog=(
            "Ошибки: InsufficientFundsError — недостаточно USD; "
            "CurrencyNotFoundError — неизвестная валюта."
        ),
    )
    buy_parser.add_argument("--currency", required=True)
    buy_parser.add_argument("--amount", required=True, type=float)

    sell_parser = commands.add_parser(
        "sell",
        description="Продажа валюты за USD.",
        epilog=(
            "Ошибки: InsufficientFundsError — недостаточно валюты; "
            "CurrencyNotFoundError — неизвестная валюта."
        ),
    )
    sell_parser.add_argument("--currency", required=True)
    sell_parser.add_argument("--amount", required=True, type=float)

    rate_parser = commands.add_parser(
        "get-rate",
        description="Получение прямого и обратного валютного курса.",
        epilog=(
            "Ошибки: CurrencyNotFoundError — неизвестная валюта; "
            "ApiRequestError — отсутствующий или устаревший курс. "
            "Поддерживаемые торговые валюты: USD, EUR, RUB, BTC, ETH."
        ),
    )
    rate_parser.add_argument("--from", dest="from_currency", required=True)
    rate_parser.add_argument("--to", dest="to_currency", required=True)

    update_parser = commands.add_parser(
        "update-rates",
        description="Загрузить свежие курсы из внешних API.",
    )
    update_parser.add_argument("--source", choices=("coingecko", "exchangerate"))

    show_rates_parser = commands.add_parser(
        "show-rates",
        description="Показать актуальные курсы из локального кеша.",
    )
    show_rates_parser.add_argument("--currency")
    show_rates_parser.add_argument("--top", type=int)
    show_rates_parser.add_argument("--base", default="USD")

    return parser


def _fresh_quotes() -> tuple[dict[str, tuple[float, datetime, str]], str]:
    """Читает и проверяет актуальные котировки относительно USD."""
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


def show_rates(
    currency: str | None = None,
    top: int | None = None,
    base: str = "USD",
) -> str:
    """Возвращает таблицу свежих курсов с фильтрами из задания."""
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
        return "Локальный кеш курсов пуст или устарел. Выполните 'update-rates'."

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
            return f"Курс для '{currency_code}' не найден в актуальном кеше."
        codes = [currency_code]

    if top is not None:
        crypto_codes = set(ParserConfig().crypto_currencies)
        codes = [code for code in codes if code in crypto_codes]
        codes.sort(key=lambda code: (-quotes[code][0], code))
        codes = codes[:top]
        if not codes:
            return "В кеше нет актуальных курсов криптовалют. Выполните 'update-rates'."

    table = PrettyTable()
    table.field_names = ["Пара", "Курс", "Источник", "Обновлено (UTC)"]
    table.align = "l"

    for code in codes:
        usd_price, updated_at, source = quotes[code]
        rate = usd_price / base_price
        if not isfinite(rate) or rate <= 0:
            continue
        rate_text = f"{rate:.8f}" if rate < 1 else f"{rate:,.2f}"
        table.add_row(
            [
                f"{code}_{base_code}",
                rate_text,
                source,
                min(updated_at, base_time).strftime("%Y-%m-%d %H:%M:%S"),
            ]
        )

    if not table.rows:
        raise ApiRequestError("Не удалось рассчитать курсы. Выполните update-rates.")

    return (
        f"Курсы из кеша (последнее обновление: {last_refresh or 'неизвестно'}):\n"
        f"{table}"
    )


def main() -> None:
    """Запускает интерактивную консоль с текущей сессией пользователя."""
    parser = create_parser()
    current_user: User | None = None
    print("CurrencyTrade Hub. Для списка команд введите help, для выхода — exit.")

    while True:
        try:
            command_line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return

        try:
            tokens = shlex.split(command_line)
        except ValueError as exc:
            print(f"Ошибка: {exc}")
            continue

        if not tokens:
            continue
        if tokens[0] in {"exit", "quit"}:
            return
        if tokens == ["help"]:
            parser.print_help()
            continue

        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            continue

        try:
            if args.command == "register":
                print(register(args.username, args.password))
            elif args.command == "login":
                current_user = login(args.username, args.password)
                print(f"Вы вошли как '{current_user.username}'")
            elif args.command == "show-portfolio":
                print(show_portfolio(current_user, args.base))
            elif args.command == "buy":
                print(buy(current_user, args.currency, args.amount))
            elif args.command == "sell":
                print(sell(current_user, args.currency, args.amount))
            elif args.command == "get-rate":
                print(get_rate(args.from_currency, args.to_currency))
            elif args.command == "update-rates":
                result = RatesUpdater().run_update(source=args.source)
                print(
                    f"Курсы обновлены: {result.updated_count}. "
                    f"Получено от API: {result.received_count}."
                )
                print(f"Последнее обновление: {result.last_refresh or 'нет'}")
                if result.errors:
                    print(
                        "Обновление завершено с ошибками. Подробности: logs/parser.log."
                    )
                    for source, message in result.errors.items():
                        print(f"- {source}: {message}")
            elif args.command == "show-rates":
                print(show_rates(args.currency, args.top, args.base))
        except InsufficientFundsError as exc:
            print(f"Ошибка сделки: {exc}")
        except CurrencyNotFoundError as exc:
            print(f"Ошибка валюты: {exc}")
            print("Поддерживаемые коды: USD, EUR, RUB, BTC, ETH.")
        except ApiRequestError as exc:
            print(f"Ошибка получения курса: {exc}")
            print("Повторите попытку позже или проверьте подключение к сети.")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print(f"Ошибка: {exc}")


if __name__ == "__main__":
    main()
