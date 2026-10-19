from abc import ABC, abstractmethod
from math import isfinite

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.config import ParserConfig


class BaseApiClient(ABC):
    """Задаёт единый интерфейс клиентов внешних источников курсов."""

    def __init__(self, config: ParserConfig | None = None) -> None:
        self.config = config if config is not None else ParserConfig()

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Возвращает курсы валют в формате FROM_TO: rate."""

    def _request_json(
        self,
        url: str,
        source: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=self.config.request_timeout,
            )
        except requests.exceptions.RequestException:
            raise ApiRequestError(
                f"{source}: ошибка сети или превышено время ожидания."
            ) from None

        if response.status_code == 429:
            raise ApiRequestError(f"{source}: превышен лимит запросов (HTTP 429).")
        if response.status_code in (401, 403):
            raise ApiRequestError(
                f"{source}: доступ запрещён (HTTP {response.status_code})."
            )
        if response.status_code != 200:
            raise ApiRequestError(
                f"{source}: сервер вернул HTTP {response.status_code}."
            )

        try:
            data = response.json()
        except ValueError:
            raise ApiRequestError(
                f"{source}: сервер вернул некорректный JSON."
            ) from None

        if not isinstance(data, dict):
            raise ApiRequestError(f"{source}: неожиданный формат ответа API.")

        return data

    @staticmethod
    def _check_rate(value: object, source: str, pair: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiRequestError(f"{source}: недопустимое значение курса {pair}.")

        rate = float(value)

        if not isfinite(rate) or rate <= 0:
            raise ApiRequestError(f"{source}: недопустимое значение курса {pair}.")

        return rate


class CoinGeckoClient(BaseApiClient):
    """Получает цены криптовалют в базовой фиатной валюте."""

    def fetch_rates(self) -> dict[str, float]:
        base = self.config.base_fiat_currency.upper()

        try:
            identifiers = {
                code: self.config.crypto_id_map[code]
                for code in self.config.crypto_currencies
            }
        except KeyError:
            raise ApiRequestError(
                "CoinGecko: в конфигурации отсутствует ID монеты."
            ) from None

        params = {
            "ids": ",".join(identifiers.values()),
            "vs_currencies": base.lower(),
        }

        headers = None

        if self.config.coingecko_demo_api_key:
            headers = {"x-cg-demo-api-key": self.config.coingecko_demo_api_key}

        data = self._request_json(
            self.config.coingecko_url,
            "CoinGecko",
            params=params,
            headers=headers,
        )

        result = {}

        for code, identifier in identifiers.items():
            values = data.get(identifier)

            if not isinstance(values, dict):
                raise ApiRequestError(f"CoinGecko: отсутствуют данные для {code}.")

            pair = f"{code}_{base}"

            result[pair] = self._check_rate(
                values.get(base.lower()),
                "CoinGecko",
                pair,
            )

        return result


class ExchangeRateApiClient(BaseApiClient):
    """Возвращает стоимость фиатных валют в базовой валюте."""

    def fetch_rates(self) -> dict[str, float]:
        key = (self.config.exchangerate_api_key or "").strip()

        if not key:
            raise ApiRequestError(
                "ExchangeRate-API: переменная EXCHANGERATE_API_KEY не задана."
            )

        base = self.config.base_fiat_currency.upper()

        url = f"{self.config.exchangerate_api_url.rstrip('/')}/{key}/latest/{base}"

        data = self._request_json(url, "ExchangeRate-API")

        if data.get("result") != "success":
            error_type = data.get(
                "error-type",
                "неизвестная ошибка",
            )
            raise ApiRequestError(f"ExchangeRate-API: запрос отклонён ({error_type}).")

        if data.get("base_code") != base:
            raise ApiRequestError("ExchangeRate-API: неожиданная базовая валюта.")

        values = data.get(
            "conversion_rates",
            data.get("rates"),
        )

        if not isinstance(values, dict):
            raise ApiRequestError("ExchangeRate-API: отсутствует словарь курсов.")

        result = {}

        for code in self.config.fiat_currencies:
            pair = f"{code}_{base}"

            direct_rate = self._check_rate(
                values.get(code),
                "ExchangeRate-API",
                pair,
            )

            result[pair] = 1.0 / direct_rate

        return result
