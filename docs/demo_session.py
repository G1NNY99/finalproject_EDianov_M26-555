import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from valutatrade_hub.cli import interface
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import get_action_logger
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater


def main() -> None:
    with TemporaryDirectory(prefix="currencytrade_demo_") as directory:
        root = Path(directory)
        for filename, initial_data in (
            ("users.json", []),
            ("portfolios.json", []),
            ("rates.json", {}),
        ):
            (root / filename).write_text(json.dumps(initial_data), encoding="utf-8")

        SettingsLoader()._settings.update(
            {
                "data_dir": str(root),
                "log_file": str(root / "actions.log"),
                "rates_ttl_seconds": 300,
            }
        )

        original_register = interface.register

        def demo_register(username: str, password: str) -> str:
            result = original_register(username, password)
            DatabaseManager().update(
                "portfolios",
                lambda portfolios: [
                    dict(portfolio, wallets={"USD": {"balance": 1000.0}})
                    for portfolio in portfolios
                ],
            )
            return result + "\nДемо: начислено 1000 USD на тестовый счёт."

        def demo_updater() -> RatesUpdater:
            return RatesUpdater(storage=RatesStorage(), logger=Mock())

        print("ДЕМО: временные JSON-файлы; реальные данные не изменяются.")
        print("Курсы загружаются из настоящих API при update-rates.")
        print("Указывайте только вымышленные логин и пароль.")

        try:
            with (
                patch.object(interface, "register", side_effect=demo_register),
                patch.object(interface, "RatesUpdater", side_effect=demo_updater),
            ):
                interface.main()
        finally:
            logger = get_action_logger()
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
                handler.close()

        print("Демонстрация завершена. Временные данные удалены.")


if __name__ == "__main__":
    main()
