from dataclasses import dataclass, field
from os import getenv
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
EXCHANGERATE_API_URL = "https://v6.exchangerate-api.com/v6"

BASE_FIAT_CURRENCY = "USD"

FIAT_CURRENCIES = ("EUR", "GBP", "RUB")
CRYPTO_CURRENCIES = ("BTC", "ETH", "SOL")

CRYPTO_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
}

REQUEST_TIMEOUT = 10


@dataclass(frozen=True, slots=True)
class ParserConfig:
    """Хранит параметры Parser Service и безопасно читает API-ключи."""

    exchangerate_api_key: str | None = field(
        default_factory=lambda: getenv("EXCHANGERATE_API_KEY")
    )
    coingecko_demo_api_key: str | None = field(
        default_factory=lambda: getenv("COINGECKO_DEMO_API_KEY")
    )

    coingecko_url: str = COINGECKO_URL
    exchangerate_api_url: str = EXCHANGERATE_API_URL

    base_fiat_currency: str = BASE_FIAT_CURRENCY

    fiat_currencies: tuple[str, ...] = FIAT_CURRENCIES
    crypto_currencies: tuple[str, ...] = CRYPTO_CURRENCIES

    crypto_id_map: dict[str, str] = field(default_factory=lambda: CRYPTO_ID_MAP.copy())

    request_timeout: int = REQUEST_TIMEOUT

    def _data_dir(self) -> Path:
        """Определяет каталог данных из настроек основного сервиса."""
        data_dir = Path(str(SettingsLoader().get("data_dir", "data")))

        if not data_dir.is_absolute():
            data_dir = Path(__file__).resolve().parents[2] / data_dir

        return data_dir

    @property
    def rates_file_path(self) -> Path:
        """Возвращает путь к локальному кешу курсов Core Service."""
        filename = SettingsLoader().get("rates_file", "rates.json")
        return self._data_dir() / str(filename)

    @property
    def history_file_path(self) -> Path:
        """Возвращает путь к истории измерений Parser Service."""
        filename = SettingsLoader().get("history_file", "exchange_rates.json")
        return self._data_dir() / str(filename)
