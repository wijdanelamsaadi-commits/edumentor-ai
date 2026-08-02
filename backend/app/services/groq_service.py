from __future__ import annotations

from app.core.config import get_settings
from app.services.ai.ai_provider import AIProviderError, AIRequest
from app.services.ai.groq_provider import GROQ_CHAT_COMPLETIONS_URL, get_ai_provider


def generate_general_answer(
    message: str,
    language: str,
    level: str,
    *,
    pedagogical_profile: list[dict] | None = None,
    intent: str | None = None,
) -> str:
    settings = get_settings()

    if not settings["groq_api_key"]:
        return _fallback_answer(language)

    try:
        response = get_ai_provider().generate_text(
            AIRequest(
                system_prompt=_system_prompt(language, level),
                user_prompt=_build_user_prompt(message, pedagogical_profile, intent),
                temperature=0.35,
                max_tokens=750,
                timeout_seconds=float(settings.get("ai_timeout_seconds") or 25),
            )
        )
    except (AIProviderError, KeyError):
        return _fallback_answer(language)

    return response.text.strip()


def _system_prompt(language: str, level: str) -> str:
    return (
        "Tu es l'assistant pedagogique de francais d'EduMentor AI, specialise dans le programme marocain "
        "de la premiere annee du baccalaureat et dans la preparation a l'examen regional. "
        "Tu accompagnes l'eleve sur La Boite a merveilles d'Ahmed Sefrioui, Antigone de Jean Anouilh, "
        "Le Dernier Jour d'un condamne de Victor Hugo, la comprehension de texte, la langue, les figures "
        "de style, la methodologie, la production ecrite et les examens regionaux. "
        f"Reponds dans la langue de l'utilisateur si elle est claire, sinon en {language}. "
        f"Adapte la difficulte et la longueur au niveau de l'eleve: {level}. "
        "Utilise en priorite les extraits et documents fournis quand ils existent. N'invente jamais une "
        "citation, un evenement, un chapitre, une correction officielle ou une source. Si les documents "
        "disponibles ne permettent pas de confirmer une information precise, indique-le clairement. "
        "Quand l'eleve propose une reponse, indique ce qui est correct, ce qui manque ou doit etre "
        "ameliore, propose une formulation amelioree et ajoute un conseil court. Pour une production "
        "ecrite, aide a comprendre le sujet, propose un plan, des arguments et des conseils sans faire "
        "tout le travail a la place de l'eleve, sauf demande explicite. Pour une question hors du "
        "francais de 1ere Bac, rappelle poliment ta specialisation. Ne mentionne jamais au public les "
        "termes techniques suivants: RAG, Groq, ChromaDB, embeddings, provider, dataset, accuracy, "
        "Macro-F1, logistic regression ou version du modele."
    )


def _build_user_prompt(message: str, pedagogical_profile: list[dict] | None, intent: str | None) -> str:
    lines: list[str] = []
    if intent:
        lines.append(f"Intention pedagogique interne: {intent}")
    if pedagogical_profile:
        lines.append("Profil pedagogique interne de l'eleve:")
        for item in pedagogical_profile:
            score = item.get("score_percentage")
            score_text = f", score moyen {score} %" if score is not None else ""
            lines.append(
                f"- {item.get('competence')}: {item.get('status')}{score_text}. "
                f"Conseil: {item.get('recommendation')}"
            )
        lines.append(
            "Utilise ce profil seulement lorsqu'il est pertinent, sans repeter mecaniquement tous les "
            "scores, sans humilier l'eleve et sans parler de prediction ou de modele."
        )
    lines.append(f"Question de l'eleve: {message}")
    return "\n".join(lines)


def _fallback_answer(language: str) -> str:
    if language == "english":
        return (
            "General answer\n\n"
            "I can help with Moroccan 1st-year baccalaureate French preparation, but the general answer "
            "service is temporarily unavailable. Please try again in a moment."
        )
    if language == "arabic":
        return (
            "اجابة عامة\n\n"
            "يمكنني مساعدتك في الفرنسية للسنة الاولى باكالوريا والتحضير للامتحان الجهوي، "
            "لكن خدمة الاجابة العامة غير متاحة مؤقتا. حاول مرة اخرى لاحقا."
        )
    if language == "darija":
        return (
            "Reponse generale\n\n"
            "نقدر نعاونك ففرنسية الاولى باك والتحضير للجهوي، ولكن خدمة الجواب العام ما خداماش دابا. "
            "عاود حاول من بعد."
        )
    return (
        "Reponse generale\n\n"
        "Je peux vous aider sur le francais de 1ere Bac et la preparation au regional, mais le service de "
        "reponse generale est momentanement indisponible. Reessayez dans un instant."
    )
