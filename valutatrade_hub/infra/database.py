from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, RLock
from typing import Any, ClassVar, Self

from valutatrade_hub.infra.settings import SettingsLoader


class DatabaseManager:
    """Единая точка доступа к JSON-хранилищам приложения."""

    _instance: ClassVar[DatabaseManager | None] = None
    _instance_lock = Lock()

    _SETTING_KEYS: ClassVar[dict[str, str]] = {
        "users": "users_file",
        "portfolios": "portfolios_file",
        "rates": "rates_file",
    }

    def __new__(cls) -> Self:
        # __new__ выбран для простоты Singleton без отдельного метакласса.
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._lock = RLock()
                cls._instance = instance

            return cls._instance

    def _get_path(self, storage: str) -> Path:
        """Возвращает путь к настроенному JSON-хранилищу."""
        setting_key = self._SETTING_KEYS.get(storage)

        if setting_key is None:
            raise ValueError(f"Неизвестное хранилище: {storage}")

        settings = SettingsLoader()
        data_dir = Path(settings.get("data_dir", "data"))

        if not data_dir.is_absolute():
            data_dir = Path(__file__).resolve().parents[2] / data_dir

        filename = settings.get(setting_key)

        return data_dir / filename

    def _read_unlocked(self, storage: str) -> Any:
        """Читает JSON без повторного захвата блокировки."""
        path = self._get_path(storage)

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write_unlocked(self, storage: str, data: Any) -> None:
        """Записывает JSON через временный файл."""
        path = self._get_path(storage)
        path.parent.mkdir(parents=True, exist_ok=True)

        content = (
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )

        temporary_path = None

        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_file.write(content)
                temporary_path = Path(temporary_file.name)

            temporary_path.replace(path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def read(self, storage: str) -> Any:
        """Возвращает данные JSON-хранилища."""
        with self._lock:
            return self._read_unlocked(storage)

    def write(self, storage: str, data: Any) -> None:
        """Сохраняет данные JSON-хранилища."""
        with self._lock:
            self._write_unlocked(storage, data)

    def update(
        self,
        storage: str,
        callback: Callable[[Any], Any],
    ) -> Any:
        """Читает, изменяет и сохраняет данные одной операцией."""
        with self._lock:
            current_data = self._read_unlocked(storage)
            updated_data = callback(current_data)
            self._write_unlocked(storage, updated_data)

            return updated_data
