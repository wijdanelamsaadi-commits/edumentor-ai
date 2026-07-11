from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.core.config import get_settings

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


def generate_general_answer(message: str, language: str, level: str) -> str:
    settings = get_settings()
    api_key = settings["groq_api_key"]

    if not api_key:
        return _fallback_answer(language)

    payload = {
        "model": settings["groq_model"],
        "temperature": 0.35,
        "max_tokens": 650,
        "messages": [
            {
                "role": "system",
                "content": _system_prompt(language, level),
            },
            {
                "role": "user",
                "content": message,
            },
        ],
    }

    request = urllib.request.Request(
        GROQ_CHAT_COMPLETIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "EduMentorAI/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        return _fallback_answer(language)

    return data["choices"][0]["message"]["content"].strip()


def _system_prompt(language: str, level: str) -> str:
    return (
        "You are EduMentor AI, an educational assistant specialized in Artificial Intelligence courses. "
        "Answer only AI-learning questions. The current question is related to AI but was not found in the local PDF corpus. "
        f"Answer in {language}. Adapt the answer to this learner level: {level}. "
        "Be clear, concise, pedagogical, and do not mention internal API details. "
        "Start with 'Réponse générale' if the language is French or Darija, 'General answer' if English, "
        "and 'إجابة عامة' if Arabic. Do not invent PDF sources."
    )


def _fallback_answer(language: str) -> str:
    if language == "english":
        return (
            "General answer\n\n"
            "I can answer this AI-related question, but the general AI service is temporarily unavailable. "
            "Please try again in a moment."
        )
    if language == "arabic":
        return (
            "إجابة عامة\n\n"
            "يمكنني الإجابة عن هذا السؤال المتعلق بالذكاء الاصطناعي، لكن خدمة الإجابات العامة غير متاحة مؤقتا. "
            "يرجى المحاولة لاحقا."
        )
    if language == "darija":
        return (
            "Réponse générale\n\n"
            "نقدر نجاوبك على هاد السؤال حيث كيتعلق بالذكاء الاصطناعي، ولكن خدمة الجواب العام ما خداماش دابا. "
            "عاود حاول من بعد."
        )
    return (
        "Réponse générale\n\n"
        "Je peux répondre à cette question liée à l'IA, mais le service de réponse générale est momentanément indisponible. "
        "Réessayez dans un instant."
    )
