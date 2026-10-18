import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load_json(filename: str) -> list | dict:
    """Загружает данные из JSON-файла каталога data."""
    file_path = DATA_DIR / filename

    with file_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(filename: str, data: list | dict) -> None:
    """Сохраняет данные в JSON-файл каталога data."""
    file_path = DATA_DIR / filename

    with file_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
