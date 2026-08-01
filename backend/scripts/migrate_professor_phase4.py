from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import engine  # noqa: E402
from app.core.professor_migration import apply_professor_migration  # noqa: E402
from app.models import persistence as persistence_models  # noqa: F401,E402


if __name__ == "__main__":
    result = apply_professor_migration(engine)
    print(json.dumps(result, ensure_ascii=False, indent=2))
