from datetime import UTC, datetime, timedelta
from math import isfinite
from secrets import token_hex

from valutatrade_hub.core.models import EXCHANGE_RATES, Portfolio, User
from valutatrade_hub.core.utils import load_json, save_json


def register(username: str, password: str) -> str:
    """Регистрирует пользователя и создаёт для него пустой портфель."""
    if not isinstance(username, str) or not username.strip():
        raise ValueError("Имя пользователя не может быть пустым")

    username = username.strip()
    users = load_json("users.json")

    if any(user["username"] == username for user in users):
        raise ValueError(f"Имя пользователя '{username}' уже занято")

    user_id = max((user["user_id"] for user in users), default=0) + 1
    salt = token_hex(16)

    user = User(
        user_id=user_id,
        username=username,
        hashed_password="",
        salt=salt,
        registration_date=datetime.now(UTC),
    )
    user.change_password(password)

    users.append(
        {
            "user_id": user.user_id,
            "username": user.username,
            "hashed_password": user.hashed_password,
            "salt": user.salt,
            "registration_date": user.registration_date.isoformat(),
        }
    )

    portfolios = load_json("portfolios.json")
    portfolios.append(
        {
            "user_id": user.user_id,
            "wallets": {},
        }
    )

    save_json("users.json", users)
    save_json("portfolios.json", portfolios)

    return (
        f"Пользователь '{user.username}' зарегистрирован "
        f"(id={user.user_id}). "
        f"Войдите: login --username {user.username} --password ****"
    )


def login(username: str, password: str) -> User:
    """Проверяет учётные данные и возвращает пользователя для сессии."""
    if not isinstance(username, str) or not username.strip():
        raise ValueError("Имя пользователя не может быть пустым")

    username = username.strip()
    users = load_json("users.json")

    for record in users:
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
    """Показывает кошельки пользователя и их общую стоимость."""
    if user is None:
        raise ValueError("Сначала выполните login")

    if not isinstance(base_currency, str) or not base_currency.strip():
        raise ValueError("Неизвестная базовая валюта ''")

    base_code = base_currency.strip().upper()

    if base_code not in EXCHANGE_RATES:
        raise ValueError(f"Неизвестная базовая валюта '{base_code}'")

    portfolios = load_json("portfolios.json")

    record = next(
        (item for item in portfolios if item["user_id"] == user.user_id),
        None,
    )

    if record is None:
        raise ValueError("Портфель пользователя не найден")

    if not record["wallets"]:
        return f"Портфель пользователя '{user.username}' пуст"

    portfolio = Portfolio(user)

    for currency_code, wallet_data in record["wallets"].items():
        portfolio.add_currency(currency_code)
        wallet = portfolio.get_wallet(currency_code)
        wallet.balance = wallet_data["balance"]

    lines = [f"Портфель пользователя '{user.username}' (база: {base_code}):"]

    for wallet in portfolio.wallets.values():
        if wallet.currency_code not in EXCHANGE_RATES:
            raise ValueError(
                f"Не удалось получить курс для {wallet.currency_code}→{base_code}"
            )

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


def buy(user: User | None, currency_code: str, amount: float) -> str:
    """Покупает валюту за USD и сохраняет обновлённые балансы."""
    if user is None:
        raise ValueError("Сначала выполните login")

    if not isinstance(currency_code, str) or not currency_code.strip():
        raise ValueError("Код валюты не может быть пустым")

    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise TypeError("'amount' должен быть числом")

    if not isfinite(amount) or amount <= 0:
        raise ValueError("'amount' должен быть положительным числом")

    code = currency_code.strip().upper()
    if code not in EXCHANGE_RATES:
        raise ValueError(f"Не удалось получить курс для {code}→USD")

    rate = EXCHANGE_RATES[code]
    cost = amount * rate
    if not isfinite(cost):
        raise ValueError("'amount' должен быть положительным числом")

    portfolios = load_json("portfolios.json")
    record = next(
        (item for item in portfolios if item["user_id"] == user.user_id),
        None,
    )
    if record is None:
        raise ValueError("Портфель пользователя не найден")

    portfolio = Portfolio(user)
    for current_code, wallet_data in record["wallets"].items():
        portfolio.add_currency(current_code)
        portfolio.get_wallet(current_code).balance = wallet_data["balance"]

    usd_wallet = portfolio.wallets.get("USD")
    available = usd_wallet.balance if usd_wallet is not None else 0.0
    if cost > available:
        raise ValueError(
            f"Недостаточно средств: доступно {available:,.2f} USD, "
            f"требуется {cost:,.2f} USD"
        )

    if code not in portfolio.wallets:
        portfolio.add_currency(code)

    target_wallet = portfolio.get_wallet(code)
    previous_balance = target_wallet.balance
    usd_wallet.withdraw(cost)
    target_wallet.deposit(amount)

    record["wallets"] = {
        wallet_code: {"balance": wallet.balance}
        for wallet_code, wallet in portfolio.wallets.items()
    }
    save_json("portfolios.json", portfolios)

    precision = 4 if code in {"BTC", "ETH"} else 2
    return (
        f"Покупка выполнена: {amount:,.{precision}f} {code} "
        f"по курсу {rate:,.2f} USD/{code}\n"
        f"Изменения в портфеле:\n"
        f"- {code}: было {previous_balance:,.{precision}f} "
        f"→ стало {target_wallet.balance:,.{precision}f}\n"
        f"Оценочная стоимость покупки: {cost:,.2f} USD"
    )


def sell(user: User | None, currency_code: str, amount: float) -> str:
    """Продаёт валюту за USD и сохраняет обновлённые балансы."""
    if user is None:
        raise ValueError("Сначала выполните login")

    if not isinstance(currency_code, str) or not currency_code.strip():
        raise ValueError("Код валюты не может быть пустым")

    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise TypeError("'amount' должен быть числом")

    if not isfinite(amount) or amount <= 0:
        raise ValueError("'amount' должен быть положительным числом")

    code = currency_code.strip().upper()
    if code == "USD":
        raise ValueError("Нельзя продать USD за USD")

    if code not in EXCHANGE_RATES:
        raise ValueError(f"Не удалось получить курс для {code}→USD")

    rate = EXCHANGE_RATES[code]
    proceeds = amount * rate
    if not isfinite(proceeds):
        raise ValueError("'amount' должен быть положительным числом")

    portfolios = load_json("portfolios.json")
    record = next(
        (item for item in portfolios if item["user_id"] == user.user_id),
        None,
    )
    if record is None:
        raise ValueError("Портфель пользователя не найден")

    portfolio = Portfolio(user)
    for current_code, wallet_data in record["wallets"].items():
        portfolio.add_currency(current_code)
        portfolio.get_wallet(current_code).balance = wallet_data["balance"]

    wallet = portfolio.wallets.get(code)
    if wallet is None:
        raise ValueError(
            f"У вас нет кошелька '{code}'. "
            "Добавьте валюту: она создаётся автоматически при первой покупке."
        )

    precision = 4 if code in {"BTC", "ETH"} else 2
    if amount > wallet.balance:
        raise ValueError(
            f"Недостаточно средств: доступно "
            f"{wallet.balance:,.{precision}f} {code}, "
            f"требуется {amount:,.{precision}f} {code}"
        )

    if "USD" not in portfolio.wallets:
        portfolio.add_currency("USD")

    usd_wallet = portfolio.get_wallet("USD")
    previous_balance = wallet.balance
    wallet.withdraw(amount)
    usd_wallet.deposit(proceeds)

    record["wallets"] = {
        wallet_code: {"balance": current_wallet.balance}
        for wallet_code, current_wallet in portfolio.wallets.items()
    }
    save_json("portfolios.json", portfolios)

    return (
        f"Продажа выполнена: {amount:,.{precision}f} {code} "
        f"по курсу {rate:,.2f} USD/{code}\n"
        f"Изменения в портфеле:\n"
        f"- {code}: было {previous_balance:,.{precision}f} "
        f"→ стало {wallet.balance:,.{precision}f}\n"
        f"Оценочная выручка: {proceeds:,.2f} USD"
    )


def get_rate(from_currency: str, to_currency: str) -> str:
    """Возвращает курс валют из свежего кеша или демонстрационной заглушки."""
    if not isinstance(from_currency, str) or not from_currency.strip():
        raise ValueError("Исходная валюта не может быть пустой")
    if not isinstance(to_currency, str) or not to_currency.strip():
        raise ValueError("Целевая валюта не может быть пустой")

    from_code = from_currency.strip().upper()
    to_code = to_currency.strip().upper()
    rates_cache = load_json("rates.json")
    now = datetime.now(UTC)
    pairs = (
        (f"{from_code}_{to_code}", False),
        (f"{to_code}_{from_code}", True),
    )

    for key, inverse in pairs:
        record = rates_cache.get(key)
        if not isinstance(record, dict):
            continue

        try:
            updated_at = datetime.fromisoformat(record["updated_at"])
            cached_rate = float(record["rate"])
        except (KeyError, TypeError, ValueError, AttributeError):
            continue

        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        if not timedelta(0) <= now - updated_at < timedelta(minutes=5):
            continue
        if not isfinite(cached_rate) or cached_rate <= 0:
            continue

        rate = 1 / cached_rate if inverse else cached_rate
        if not isfinite(rate) or rate <= 0 or not isfinite(1 / rate):
            continue
        break
    else:
        if from_code not in EXCHANGE_RATES or to_code not in EXCHANGE_RATES:
            raise ValueError(
                f"Курс {from_code}→{to_code} недоступен. Повторите попытку позже."
            )
        rate = EXCHANGE_RATES[from_code] / EXCHANGE_RATES[to_code]
        updated_at = now
        rates_cache[f"{from_code}_{to_code}"] = {
            "rate": rate,
            "updated_at": now.isoformat(),
        }
        rates_cache["source"] = "Stub"
        rates_cache["last_refresh"] = now.isoformat()
        save_json("rates.json", rates_cache)

    reverse_rate = 1 / rate
    rate_text = f"{rate:.8f}" if rate < 1 else f"{rate:.2f}"
    reverse_text = f"{reverse_rate:.8f}" if reverse_rate < 1 else f"{reverse_rate:.2f}"

    return (
        f"Курс {from_code}→{to_code}: {rate_text} "
        f"(обновлено: {updated_at:%Y-%m-%d %H:%M:%S} UTC)\n"
        f"Обратный курс {to_code}→{from_code}: {reverse_text}"
    )
