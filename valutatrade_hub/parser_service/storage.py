import json
import os
import re
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from valutatrade_hub.parser_service.config import ParserConfig

_PAIR_PATTERN = re.compile(r"^[A-Z]{2,5}_[A-Z]{2,5}$")


class RatesStorage:
    """Сохраняет последние валютные курсы и историю измерений."""

    def __init__(self, config: ParserConfig | None = None) -> None:
        self.config = config if config is not None else ParserConfig()
        self._lock = RLock()

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Время обновления должно содержать часовой пояс.")

        return (
            value.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _as_datetime(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("Некорректное время обновления курса.") from None

        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Время курса должно содержать часовой пояс.")

        return parsed.astimezone(UTC)

    @staticmethod
    def _read_json(path: Path, default: object) -> object:
        if not path.exists():
            return default

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    @staticmethod
    def _write_json(path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None

        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temp_name = Path(file.name)
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            os.replace(temp_name, path)
        finally:
            if temp_name is not None:
                temp_name.unlink(missing_ok=True)

    def load_cache(self) -> dict:
        """Читает последний снимок курсов."""
        with self._lock:
            value = self._read_json(
                self.config.rates_file_path,
                {"pairs": {}, "last_refresh": None},
            )

            if not isinstance(value, dict):
                raise TypeError("Файл курсов должен содержать JSON-объект.")

            if not value:
                return {"pairs": {}, "last_refresh": None}

            if not isinstance(value.get("pairs"), dict):
                raise TypeError("Файл курсов не содержит объект pairs.")

            return value

    def load_history(self) -> list[dict]:
        """Читает журнал измерений курсов."""
        with self._lock:
            value = self._read_json(self.config.history_file_path, [])

            if not isinstance(value, list):
                raise TypeError("История курсов должна содержать JSON-массив.")

            return value

    def save_rates(
        self,
        entries: dict[str, dict[str, object]],
        *,
        timestamp: datetime | None = None,
    ) -> int:
        """Обновляет снимок курсов и журнал измерений."""
        if not isinstance(entries, dict):
            raise TypeError("Ожидается словарь валютных пар.")

        recorded_at = self._timestamp(
            timestamp if timestamp is not None else datetime.now(UTC)
        )

        records = []

        for pair, details in entries.items():
            if not isinstance(pair, str) or not _PAIR_PATTERN.fullmatch(pair):
                raise ValueError(f"Некорректная валютная пара: {pair!r}.")

            if not isinstance(details, dict):
                raise TypeError(f"Данные пары {pair} должны быть словарём.")

            rate = details.get("rate")
            source = details.get("source")
            meta = details.get("meta", {})

            if (
                isinstance(rate, bool)
                or not isinstance(rate, (int, float))
                or not isfinite(rate)
                or rate <= 0
            ):
                raise ValueError(f"Некорректный курс для {pair}.")

            if not isinstance(source, str) or not source.strip():
                raise ValueError(f"Не указан источник курса {pair}.")

            if not isinstance(meta, dict):
                raise TypeError(f"Некорректные метаданные курса {pair}.")

            from_code, to_code = pair.split("_")

            records.append(
                {
                    "id": f"{pair}_{recorded_at}",
                    "from_currency": from_code,
                    "to_currency": to_code,
                    "rate": float(rate),
                    "timestamp": recorded_at,
                    "source": source,
                    "meta": meta.copy(),
                }
            )

        if not records:
            return 0

        with self._lock:
            cache = self.load_cache()
            history = self.load_history()

            existing_ids = {row.get("id") for row in history if isinstance(row, dict)}

            updated = 0
            history_changed = False

            for record in records:
                pair = f"{record['from_currency']}_{record['to_currency']}"

                if record["id"] not in existing_ids:
                    history.append(record)
                    existing_ids.add(record["id"])
                    history_changed = True

                previous = cache["pairs"].get(pair)

                if previous is not None:
                    if not isinstance(previous, dict):
                        raise TypeError(f"Некорректная запись кэша для {pair}.")

                    old_time = previous.get("updated_at")

                    if not isinstance(old_time, str):
                        raise TypeError(f"Не указано время кэша для {pair}.")

                    if self._as_datetime(old_time) >= self._as_datetime(
                        record["timestamp"]
                    ):
                        continue

                cache["pairs"][pair] = {
                    "rate": record["rate"],
                    "updated_at": record["timestamp"],
                    "source": record["source"],
                }

                updated += 1

            if history_changed:
                self._write_json(self.config.history_file_path, history)

            if updated:
                previous_refresh = cache.get("last_refresh")

                if not isinstance(previous_refresh, str) or (
                    self._as_datetime(recorded_at) > self._as_datetime(previous_refresh)
                ):
                    cache["last_refresh"] = recorded_at

                self._write_json(self.config.rates_file_path, cache)

            return updated
