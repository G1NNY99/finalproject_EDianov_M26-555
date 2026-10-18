from __future__ import annotations

import tomllib
from pathlib import Path
from threading import Lock
from typing import Any, ClassVar, Self


class SettingsLoader:
    """Единый экземпляр для загрузки и кеширования конфигурации проекта."""

    _instance: ClassVar[SettingsLoader | None] = None
    _lock = Lock()

    def __new__(cls) -> Self:
        # __new__ выбран для простоты Singleton без отдельного метакласса.
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._config_path = (
                    Path(__file__).resolve().parents[2] / "pyproject.toml"
                )
                instance._settings = instance._read_settings()
                cls._instance = instance

            return cls._instance

    def _read_settings(self) -> dict[str, Any]:
        """Читает настройки приложения из pyproject.toml."""
        with self._config_path.open("rb") as file:
            config = tomllib.load(file)

        return config["tool"]["valutatrade"]

    def get(self, key: str, default: Any = None) -> Any:
        """Возвращает значение настройки или значение по умолчанию."""
        return self._settings.get(key, default)

    def reload(self) -> None:
        """Повторно загружает конфигурацию из файла."""
        settings = self._read_settings()

        with self._lock:
            self._settings = settings
