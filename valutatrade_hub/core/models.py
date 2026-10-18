from datetime import datetime
from hashlib import sha256
from hmac import compare_digest
from math import isfinite

EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 1.0786,
    "BTC": 59337.21,
    "RUB": 0.01016,
    "ETH": 3720.0,
}


class User:
    """Пользователь платформы с хешированным паролем."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        self._user_id = user_id
        self._username = ""
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @property
    def user_id(self) -> int:
        """Возвращает идентификатор пользователя."""
        return self._user_id

    @property
    def username(self) -> str:
        """Возвращает имя пользователя."""
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым")
        self._username = value.strip()

    @property
    def hashed_password(self) -> str:
        """Возвращает сохранённый хеш пароля."""
        return self._hashed_password

    @property
    def salt(self) -> str:
        """Возвращает соль для хеширования пароля."""
        return self._salt

    @property
    def registration_date(self) -> datetime:
        """Возвращает дату регистрации."""
        return self._registration_date

    def get_user_info(self) -> dict[str, int | str]:
        """Возвращает сведения о пользователе без пароля и его хеша."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "registration_date": self._registration_date.isoformat(),
        }

    def change_password(self, new_password: str) -> None:
        """Проверяет пароль и сохраняет его хеш с солью."""
        if not isinstance(new_password, str) or len(new_password) < 4:
            raise ValueError("Пароль должен быть не короче 4 символов")
        self._hashed_password = sha256(
            (new_password + self._salt).encode("utf-8")
        ).hexdigest()

    def verify_password(self, password: str) -> bool:
        """Проверяет соответствие пароля сохранённому хешу."""
        if not isinstance(password, str):
            return False
        password_hash = sha256((password + self._salt).encode("utf-8")).hexdigest()
        return compare_digest(password_hash, self._hashed_password)


class Wallet:
    """Кошелёк пользователя для одной валюты."""

    def __init__(
        self,
        currency_code: str,
        balance: float = 0.0,
    ) -> None:
        if not isinstance(currency_code, str) or not currency_code.strip():
            raise ValueError("Код валюты не может быть пустым")

        self.currency_code = currency_code.strip().upper()
        self._balance = 0.0
        self.balance = balance

    @property
    def balance(self) -> float:
        """Возвращает текущий баланс."""
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("Баланс должен быть числом")

        if not isfinite(value) or value < 0:
            raise ValueError("Баланс должен быть конечным неотрицательным числом")

        self._balance = float(value)

    def deposit(self, amount: float) -> None:
        """Пополняет баланс кошелька."""
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise TypeError("'amount' должен быть числом")

        if not isfinite(amount) or amount <= 0:
            raise ValueError("'amount' должен быть положительным числом")

        self.balance += amount

    def withdraw(self, amount: float) -> None:
        """Снимает средства с кошелька."""
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise TypeError("'amount' должен быть числом")

        if not isfinite(amount) or amount <= 0:
            raise ValueError("'amount' должен быть положительным числом")

        if amount > self.balance:
            raise ValueError("Недостаточно средств")

        self.balance -= amount

    def get_balance_info(self) -> dict[str, str | float]:
        """Возвращает информацию о валюте и балансе."""
        return {
            "currency_code": self.currency_code,
            "balance": self.balance,
        }


class Portfolio:
    """Портфель валютных кошельков одного пользователя."""

    def __init__(
        self,
        user: User,
        wallets: dict[str, Wallet] | None = None,
    ) -> None:
        self._user = user
        self._user_id = user.user_id
        self._wallets = wallets.copy() if wallets is not None else {}

    @property
    def user(self) -> User:
        """Возвращает владельца портфеля."""
        return self._user

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Возвращает копию словаря кошельков."""
        return self._wallets.copy()

    def add_currency(self, currency_code: str) -> None:
        """Добавляет кошелёк, если валюта ещё не представлена."""
        wallet = Wallet(currency_code)
        if wallet.currency_code in self._wallets:
            raise ValueError(
                f"Кошелёк для валюты '{wallet.currency_code}' уже существует"
            )
        self._wallets[wallet.currency_code] = wallet

    def get_wallet(self, currency_code: str) -> Wallet:
        """Возвращает кошелёк по коду валюты."""
        if not isinstance(currency_code, str) or not currency_code.strip():
            raise ValueError("Код валюты не может быть пустым")
        return self._wallets[currency_code.strip().upper()]

    def get_total_value(
        self,
        base_currency: str = "USD",
        exchange_rates: dict[str, float] | None = None,
    ) -> float:
        """Вычисляет стоимость портфеля в выбранной базовой валюте."""
        rates = EXCHANGE_RATES if exchange_rates is None else exchange_rates
        if not isinstance(base_currency, str) or not base_currency.strip():
            raise ValueError("Базовая валюта не может быть пустой")

        base_code = base_currency.strip().upper()
        if base_code not in rates:
            raise ValueError(f"Неизвестная базовая валюта '{base_code}'")

        total = 0.0
        for wallet in self._wallets.values():
            if wallet.currency_code not in rates:
                raise ValueError(
                    f"Не удалось получить курс для {wallet.currency_code}→{base_code}"
                )
            total += wallet.balance * rates[wallet.currency_code] / rates[base_code]

        return total
