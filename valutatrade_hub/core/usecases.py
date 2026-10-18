from datetime import UTC, datetime, timedelta
from math import isfinite
from secrets import token_hex

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.models import EXCHANGE_RATES, Portfolio, User
from valutatrade_hub.decorators import log_action, set_action_context
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


def _require_user(user: User | None) -> User:
    """Проверяет наличие авторизованного пользователя."""
    if user is None:
        raise ValueError("Сначала выполните login")
    return user


def _validate_amount(amount: float) -> None:
    """Проверяет, что сумма является положительным конечным числом."""
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise TypeError("'amount' должен быть числом")
    if not isfinite(amount) or amount <= 0:
        raise ValueError("'amount' должен быть положительным числом")


def _find_record(portfolios: list[dict], user_id: int) -> dict:
    """Находит сохранённый портфель пользователя."""
    record = next(
        (item for item in portfolios if item["user_id"] == user_id),
        None,
    )
    if record is None:
        raise ValueError("Портфель пользователя не найден")
    return record


def _restore_portfolio(user: User, record: dict) -> Portfolio:
    """Восстанавливает валютные кошельки из JSON-данных."""
    portfolio = Portfolio(user)

    for currency_code, wallet_data in record["wallets"].items():
        code = get_currency(currency_code).code
        portfolio.add_currency(code)
        portfolio.get_wallet(code).balance = wallet_data["balance"]

    return portfolio


def _save_wallets(record: dict, portfolio: Portfolio) -> None:
    """Сохраняет балансы кошельков в запись портфеля."""
    record["wallets"] = {
        code: {"balance": wallet.balance} for code, wallet in portfolio.wallets.items()
    }


def register(username: str, password: str) -> str:
    """Регистрирует пользователя и создаёт ему пустой портфель."""
    if not isinstance(username, str) or not username.strip():
        raise ValueError("Имя пользователя не может быть пустым")

    username = username.strip()
    created_user: User | None = None
    database = DatabaseManager()

    def add_user(users: list[dict]) -> list[dict]:
        nonlocal created_user

        if any(user["username"] == username for user in users):
            raise ValueError(f"Имя пользователя '{username}' уже занято")

        user_id = max((user["user_id"] for user in users), default=0) + 1

        created_user = User(
            user_id=user_id,
            username=username,
            hashed_password="",
            salt=token_hex(16),
            registration_date=datetime.now(UTC),
        )
        created_user.change_password(password)

        users.append(
            {
                "user_id": created_user.user_id,
                "username": created_user.username,
                "hashed_password": created_user.hashed_password,
                "salt": created_user.salt,
                "registration_date": created_user.registration_date.isoformat(),
            }
        )
        return users

    database.update("users", add_user)

    def add_portfolio(portfolios: list[dict]) -> list[dict]:
        portfolios.append(
            {
                "user_id": created_user.user_id,
                "wallets": {},
            }
        )
        return portfolios

    database.update("portfolios", add_portfolio)

    return (
        f"Пользователь '{created_user.username}' зарегистрирован "
        f"(id={created_user.user_id}). "
        f"Войдите: login --username {created_user.username} --password ****"
    )


def login(username: str, password: str) -> User:
    """Проверяет учётные данные и возвращает пользователя для сессии."""
    if not isinstance(username, str) or not username.strip():
        raise ValueError("Имя пользователя не может быть пустым")

    username = username.strip()

    for record in DatabaseManager().read("users"):
        if record["username"] != username:
            continue

        user = User(
            user_id=record["user_id"],
            username=record["username"],
            hashed_password=record["hashed_password"],
            salt=record["salt"],
            registration_date=datetime.fromisoformat(record["registration_date"]),
        )

        if not user.verify_password(password):
            raise ValueError("Неверный пароль")

        return user

    raise ValueError(f"Пользователь '{username}' не найден")


def show_portfolio(
    user: User | None,
    base_currency: str = "USD",
) -> str:
    """Показывает кошельки пользователя и их стоимость в базовой валюте."""
    user = _require_user(user)

    if not isinstance(base_currency, str) or not base_currency.strip():
        raise ValueError("Неизвестная базовая валюта ''")

    base_code = get_currency(base_currency).code
    portfolios = DatabaseManager().read("portfolios")
    record = _find_record(portfolios, user.user_id)

    if not record["wallets"]:
        return f"Портфель пользователя '{user.username}' пуст"

    portfolio = _restore_portfolio(user, record)

    lines = [f"Портфель пользователя '{user.username}' (база: {base_code}):"]

    for wallet in portfolio.wallets.values():
        rate = EXCHANGE_RATES[wallet.currency_code] / EXCHANGE_RATES[base_code]
        value = wallet.balance * rate
        precision = 4 if wallet.currency_code in {"BTC", "ETH"} else 2

        lines.append(
            f"- {wallet.currency_code}: "
            f"{wallet.balance:,.{precision}f} "
            f"→ {value:,.2f} {base_code}"
        )

    lines.append("-" * 33)
    lines.append(f"ИТОГО: {portfolio.get_total_value(base_code):,.2f} {base_code}")

    return "\n".join(lines)


@log_action("BUY")
def buy(user: User | None, currency_code: str, amount: float) -> str:
    """Покупает валюту за USD и сохраняет обновлённые балансы."""
    user = _require_user(user)

    if not isinstance(currency_code, str) or not currency_code.strip():
        raise ValueError("Код валюты не может быть пустым")

    _validate_amount(amount)

    code = get_currency(currency_code).code

    if code == "USD":
        raise ValueError("Нельзя купить USD за USD")

    rate = EXCHANGE_RATES[code]
    set_action_context(rate=rate, base="USD")
    cost = amount * rate

    if not isfinite(cost):
        raise ValueError("'amount' должен быть положительным числом")

    summary = ""

    def apply_purchase(portfolios: list[dict]) -> list[dict]:
        nonlocal summary

        record = _find_record(portfolios, user.user_id)
        portfolio = _restore_portfolio(user, record)

        usd_wallet = portfolio.wallets.get("USD")
        available = usd_wallet.balance if usd_wallet is not None else 0.0

        if cost > available:
            raise InsufficientFundsError(available, cost, "USD")

        if code not in portfolio.wallets:
            portfolio.add_currency(code)

        target_wallet = portfolio.get_wallet(code)
        previous_balance = target_wallet.balance

        usd_wallet.withdraw(cost)
        target_wallet.deposit(amount)

        _save_wallets(record, portfolio)

        precision = 4 if code in {"BTC", "ETH"} else 2

        summary = (
            f"Покупка выполнена: {amount:,.{precision}f} {code} "
            f"по курсу {rate:,.2f} USD/{code}\n"
            f"Изменения в портфеле:\n"
            f"- {code}: было {previous_balance:,.{precision}f} "
            f"→ стало {target_wallet.balance:,.{precision}f}\n"
            f"Оценочная стоимость покупки: {cost:,.2f} USD"
        )
        return portfolios

    DatabaseManager().update("portfolios", apply_purchase)

    return summary


@log_action("SELL")
def sell(user: User | None, currency_code: str, amount: float) -> str:
    """Продаёт валюту за USD и сохраняет обновлённые балансы."""
    user = _require_user(user)

    if not isinstance(currency_code, str) or not currency_code.strip():
        raise ValueError("Код валюты не может быть пустым")

    _validate_amount(amount)

    code = get_currency(currency_code).code

    if code == "USD":
        raise ValueError("Нельзя продать USD за USD")

    rate = EXCHANGE_RATES[code]
    set_action_context(rate=rate, base="USD")
    proceeds = amount * rate

    if not isfinite(proceeds):
        raise ValueError("'amount' должен быть положительным числом")

    summary = ""

    def apply_sale(portfolios: list[dict]) -> list[dict]:
        nonlocal summary

        record = _find_record(portfolios, user.user_id)
        portfolio = _restore_portfolio(user, record)

        wallet = portfolio.wallets.get(code)
        available = wallet.balance if wallet is not None else 0.0

        if amount > available:
            raise InsufficientFundsError(available, amount, code)

        if "USD" not in portfolio.wallets:
            portfolio.add_currency("USD")

        usd_wallet = portfolio.get_wallet("USD")
        previous_balance = wallet.balance

        wallet.withdraw(amount)
        usd_wallet.deposit(proceeds)

        _save_wallets(record, portfolio)

        precision = 4 if code in {"BTC", "ETH"} else 2

        summary = (
            f"Продажа выполнена: {amount:,.{precision}f} {code} "
            f"по курсу {rate:,.2f} USD/{code}\n"
            f"Изменения в портфеле:\n"
            f"- {code}: было {previous_balance:,.{precision}f} "
            f"→ стало {wallet.balance:,.{precision}f}\n"
            f"Оценочная выручка: {proceeds:,.2f} USD"
        )
        return portfolios

    DatabaseManager().update("portfolios", apply_sale)

    return summary


def get_rate(from_currency: str, to_currency: str) -> str:
    """Возвращает курс из свежего кеша либо демонстрационной заглушки."""
    if not isinstance(from_currency, str) or not from_currency.strip():
        raise ValueError("Исходная валюта не может быть пустой")

    if not isinstance(to_currency, str) or not to_currency.strip():
        raise ValueError("Целевая валюта не может быть пустой")

    from_code = get_currency(from_currency).code
    to_code = get_currency(to_currency).code

    database = DatabaseManager()
    cache = database.read("rates")
    now = datetime.now(UTC)

    ttl_seconds = SettingsLoader().get("rates_ttl_seconds", 300)

    if not isinstance(ttl_seconds, (int, float)) or not isfinite(ttl_seconds):
        raise ValueError("TTL курсов должен быть конечным числом")

    if ttl_seconds < 0:
        raise ValueError("TTL курсов не может быть отрицательным")

    ttl = timedelta(seconds=ttl_seconds)
    rate: float | None = None
    updated_at = now

    for key, inverse in (
        (f"{from_code}_{to_code}", False),
        (f"{to_code}_{from_code}", True),
    ):
        record = cache.get(key)

        if not isinstance(record, dict):
            continue

        try:
            cached_at = datetime.fromisoformat(record["updated_at"])
            cached_rate = float(record["rate"])
        except (KeyError, TypeError, ValueError, AttributeError):
            continue

        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=UTC)

        if not timedelta(0) <= now - cached_at < ttl:
            continue

        if not isfinite(cached_rate) or cached_rate <= 0:
            continue

        candidate = 1 / cached_rate if inverse else cached_rate

        if not isfinite(candidate) or candidate <= 0 or not isfinite(1 / candidate):
            continue

        rate = candidate
        updated_at = cached_at
        break

    if rate is None:
        rate = EXCHANGE_RATES[from_code] / EXCHANGE_RATES[to_code]

        def refresh(rates: dict) -> dict:
            rates[f"{from_code}_{to_code}"] = {
                "rate": rate,
                "updated_at": now.isoformat(),
            }
            rates["source"] = "Stub"
            rates["last_refresh"] = now.isoformat()
            return rates

        database.update("rates", refresh)

    reverse_rate = 1 / rate
    rate_text = f"{rate:.8f}" if rate < 1 else f"{rate:.2f}"
    reverse_text = f"{reverse_rate:.8f}" if reverse_rate < 1 else f"{reverse_rate:.2f}"

    return (
        f"Курс {from_code}→{to_code}: {rate_text} "
        f"(обновлено: {updated_at:%Y-%m-%d %H:%M:%S} UTC)\n"
        f"Обратный курс {to_code}→{from_code}: {reverse_text}"
    )
