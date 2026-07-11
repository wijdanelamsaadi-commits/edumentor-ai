import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.mock_data import COURSES


def is_openable(chapter: dict) -> bool:
    if isinstance(chapter.get("openable"), bool):
        return chapter["openable"]

    status = str(chapter.get("status") or "").strip().lower()
    return chapter.get("completed") is True or status in {"completed", "active"}


def main() -> None:
    for course in COURSES:
        print(f"\n{course['id']} - {course['title']}")
        for index, chapter in enumerate(course["chapters"], start=1):
            print(
                f"{index}. {chapter['title']} | "
                f"status={chapter.get('status')} | "
                f"completed={chapter.get('completed')} | "
                f"openable={is_openable(chapter)}"
            )


if __name__ == "__main__":
    main()
