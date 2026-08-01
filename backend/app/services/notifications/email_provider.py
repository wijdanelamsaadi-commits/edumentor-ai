from __future__ import annotations

import os


def send_email(to_email: str, subject: str, body: str) -> dict:
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_FROM")
    if not host or not sender:
        return {"status": "pending_configuration", "provider": "smtp", "error_message": "SMTP non configure"}
    return {"status": "pending", "provider": "smtp", "error_message": None}
