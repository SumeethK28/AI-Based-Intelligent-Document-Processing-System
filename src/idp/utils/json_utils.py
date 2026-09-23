import json
from dataclasses import asdict
from pathlib import Path
from typing import Any


def save_dataclass_json(data: Any, output_path: str | Path) -> None:

    output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(asdict(data), file, indent=4, ensure_ascii=False)