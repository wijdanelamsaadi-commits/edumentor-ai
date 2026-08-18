from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NlpSettings:
    package_root: Path
    models_dir: Path
    data_dir: Path
    max_text_length: int = 12000


PACKAGE_ROOT = Path(__file__).resolve().parent
settings = NlpSettings(
    package_root=PACKAGE_ROOT,
    models_dir=PACKAGE_ROOT / "models",
    data_dir=PACKAGE_ROOT / "data",
)
