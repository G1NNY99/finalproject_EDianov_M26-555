import argparse
import shlex

from valutatrade_hub.core.models import User
from valutatrade_hub.core.usecases import (
    buy,
    get_rate,
    login,
    register,
    sell,
    show_portfolio,
)


def create_parser() -> argparse.ArgumentParser:
    """Создаёт парсер команд платформы."""
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

    buy_parser = commands.add_parser("buy")
    buy_parser.add_argument("--currency", required=True)
    buy_parser.add_argument("--amount", required=True, type=float)

    sell_parser = commands.add_parser("sell")
    sell_parser.add_argument("--currency", required=True)
    sell_parser.add_argument("--amount", required=True, type=float)

    rate_parser = commands.add_parser("get-rate")
    rate_parser.add_argument("--from", dest="from_currency", required=True)
    rate_parser.add_argument("--to", dest="to_currency", required=True)

    return parser


def main() -> None:
    """Запускает интерактивную консоль с текущей сессией пользователя."""
    parser = create_parser()
    current_user: User | None = None
    print("ValutaTrade Hub. Для списка команд введите help, для выхода — exit.")

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
        except (ValueError, TypeError, KeyError, FileNotFoundError) as exc:
            print(f"Ошибка: {exc}")


if __name__ == "__main__":
    main()
