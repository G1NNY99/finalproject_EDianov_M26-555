import logging
import re
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from math import isfinite
from pathlib import Path

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.storage import RatesStorage

_PAIR_PATTERN = re.compile(r"^[A-Z]{2,5}_[A-Z]{2,5}$")
_SOURCE_NAMES = {
    "coingecko": "CoinGecko",
    "exchangerate": "ExchangeRate-API",
}


def get_parser_logger() -> logging.Logger:
    """Создаёт файловый журнал Parser Service."""
    logger = logging.getLogger("valutatrade.parser")

    if logger.handlers:
        return logger

    filename = SettingsLoader().get("parser_log_file", "logs/parser.log")
    path = Path(str(filename))

    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path

    path.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        path,
        maxBytes=1_048_576,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """Содержит результат обновления валютных курсов."""

    received_count: int
    updated_count: int
    last_refresh: str | None
    errors: dict[str, str]


class RatesUpdater:
    """Объединяет курсы внешних API и сохраняет их в локальном хранилище."""

    def __init__(
        self,
        clients: dict[str, BaseApiClient] | None = None,
        storage: RatesStorage | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.clients = (
            dict(clients)
            if clients is not None
            else {
                "coingecko": CoinGeckoClient(),
                "exchangerate": ExchangeRateApiClient(),
            }
        )
        self.storage = storage if storage is not None else RatesStorage()
        self.logger = logger if logger is not None else get_parser_logger()

    @staticmethod
    def _prepare_rates(
        rates: dict[str, float],
        source_name: str,
        known_pairs: dict[str, dict[str, object]],
    ) -> dict[str, dict[str, object]]:
        if not isinstance(rates, dict):
            raise TypeError(f"{source_name}: ожидается словарь курсов.")

        batch: dict[str, dict[str, object]] = {}

        for pair, rate in rates.items():
            if not isinstance(pair, str) or not _PAIR_PATTERN.fullmatch(pair):
                raise ValueError(f"{source_name}: некорректная пара {pair!r}.")

            if (
                isinstance(rate, bool)
                or not isinstance(rate, (int, float))
                or not isfinite(rate)
                or rate <= 0
            ):
                raise ValueError(f"{source_name}: некорректный курс {pair}.")

            if pair in known_pairs:
                raise ValueError(
                    f"{source_name}: пара {pair} уже получена из другого источника."
                )

            batch[pair] = {"rate": float(rate), "source": source_name}

        return batch

    def run_update(self, source: str | None = None) -> UpdateResult:
        """Обновляет все источники или один выбранный, сохраняя частичный успех."""
        if source is None:
            selected_clients = self.clients.items()
        else:
            source = source.strip().lower()

            if source not in self.clients:
                allowed = ", ".join(self.clients)
                raise ValueError(
                    f"Неизвестный источник {source!r}. Доступны: {allowed}."
                )

            selected_clients = [(source, self.clients[source])]

        self.logger.info("Начало обновления валютных курсов.")
        entries: dict[str, dict[str, object]] = {}
        errors: dict[str, str] = {}

        for source_key, client in selected_clients:
            source_name = _SOURCE_NAMES.get(source_key, source_key)
            self.logger.info("Получение курсов: %s.", source_name)

            try:
                rates = client.fetch_rates()
                batch = self._prepare_rates(rates, source_name, entries)
            except (
                ApiRequestError,
                TypeError,
                ValueError,
                KeyError,
                OSError,
                RuntimeError,
            ) as exc:
                errors[source_key] = str(exc)
                self.logger.error("Ошибка %s: %s", source_name, exc)
                continue

            entries.update(batch)
            self.logger.info(
                "Источник %s: успешно получено %d курсов.",
                source_name,
                len(batch),
            )

        if not entries:
            self.logger.error(
                "Обновление не выполнено: ни один источник не вернул курсы."
            )
            raise ApiRequestError("Не удалось получить курсы ни из одного источника.")

        self.logger.info("Сохранение %d курсов в локальный кеш.", len(entries))

        try:
            updated_count = self.storage.save_rates(entries)
            last_refresh = self.storage.load_cache().get("last_refresh")
        except (OSError, TypeError, ValueError) as exc:
            self.logger.error("Ошибка сохранения курсов: %s", exc)
            raise

        if errors:
            self.logger.warning("Обновление завершено с ошибками некоторых источников.")

        self.logger.info(
            "Обновление завершено: получено %d, сохранено %d, ошибок %d.",
            len(entries),
            updated_count,
            len(errors),
        )
        return UpdateResult(
            received_count=len(entries),
            updated_count=updated_count,
            last_refresh=last_refresh,
            errors=errors,
        )
