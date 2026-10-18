import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock

from valutatrade_hub.infra.settings import SettingsLoader

_LOGGER_NAME = "valutatrade.actions"
_CONFIG_LOCK = Lock()


def get_action_logger() -> logging.Logger:
    """Создаёт или возвращает настроенный журнал доменных операций."""
    logger = logging.getLogger(_LOGGER_NAME)

    with _CONFIG_LOCK:
        if logger.handlers:
            return logger

        settings = SettingsLoader()

        log_format = str(settings.get("log_format", "text")).lower()

        if log_format != "text":
            raise ValueError(f"Неподдерживаемый формат логирования: {log_format}")

        level_name = str(settings.get("log_level", "INFO")).upper()

        if level_name not in {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }:
            raise ValueError(f"Неизвестный уровень логирования: {level_name}")

        log_path = Path(settings.get("log_file", "logs/actions.log"))

        if not log_path.is_absolute():
            log_path = Path(__file__).resolve().parents[1] / log_path

        log_path.parent.mkdir(parents=True, exist_ok=True)

        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_048_576,
            backupCount=3,
            encoding="utf-8",
        )

        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

        logger.setLevel(getattr(logging, level_name))
        logger.addHandler(handler)
        logger.propagate = False

    return logger
