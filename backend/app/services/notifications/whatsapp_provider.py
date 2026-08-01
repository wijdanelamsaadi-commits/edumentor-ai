from __future__ import annotations

import os


def send_whatsapp(phone_number: str | None, message: str) -> dict:
    token = os.getenv("WHATSAPP_API_TOKEN")
    provider_url = os.getenv("WHATSAPP_API_URL")
    if not token or not provider_url or not phone_number:
        return {"status": "pending_configuration", "provider": "whatsapp_api", "error_message": "WhatsApp non configure"}
    return {"status": "pending", "provider": "whatsapp_api", "error_message": None}
