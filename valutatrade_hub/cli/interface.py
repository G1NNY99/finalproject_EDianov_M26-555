import argparse
import shlex

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
from valutatrade_hub.parser_service.rate_queries import query_rates
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


def show_rates(
    currency: str | None = None,
    top: int | None = None,
    base: str = "USD",
) -> str:
    """Представляет котировки, полученные от Parser Service, в таблице CLI."""
    listing = query_rates(currency=currency, top=top, base=base)

    if listing.message is not None:
        return listing.message

    table = PrettyTable()
    table.field_names = ["Пара", "Курс", "Источник", "Обновлено (UTC)"]
    table.align = "l"

    for quote in listing.quotes:
        rate_text = f"{quote.rate:.8f}" if quote.rate < 1 else f"{quote.rate:,.2f}"
        table.add_row(
            [
                quote.pair,
                rate_text,
                quote.source,
                quote.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            ]
        )

    return (
        f"Курсы из кеша (последнее обновление: "
        f"{listing.last_refresh or 'неизвестно'}):\n{table}"
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
