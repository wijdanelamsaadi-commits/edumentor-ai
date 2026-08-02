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
        "Tu es l'assistant pédagogique de français d'EduMentor AI, spécialisé dans le programme marocain "
        "de la première année du baccalauréat et dans la préparation à l'examen régional. "
        "Tu accompagnes l'élève sur La Boîte à merveilles d'Ahmed Sefrioui, Antigone de Jean Anouilh, "
        "Le Dernier Jour d'un condamné de Victor Hugo, la compréhension de texte, la langue, les figures "
        "de style, la méthodologie, la production écrite et les examens régionaux. "
        f"Reponds dans la langue de l'utilisateur si elle est claire, sinon en {language}. "
        f"Adapte la difficulte et la longueur au niveau de l'eleve: {level}. "
        "Utilise en priorite les extraits et documents fournis quand ils existent. N'invente jamais une "
        "citation, un evenement, un chapitre, une correction officielle ou une source. Si les documents "
        "disponibles ne permettent pas de confirmer une information precise, indique-le clairement. "
        "Reponds toujours a la derniere question utilisateur: le contexte precedent sert uniquement a "
        "comprendre une reference ambigue et ne doit jamais remplacer la demande actuelle. "
        "Quand l'élève propose une réponse, indique ce qui est correct, ce qui manque ou doit être "
        "amélioré, propose une formulation améliorée et ajoute un conseil court. Pour une production "
        "écrite, aide à comprendre le sujet, propose un plan, des arguments et des conseils sans faire "
        "tout le travail a la place de l'eleve, sauf demande explicite. Pour une question hors du "
        "français de 1ère Bac, rappelle poliment ta spécialisation. Ne mentionne jamais au public les "
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
        "Je peux vous aider sur le français de 1ère Bac et la préparation au régional, mais le service de "
        "réponse générale est momentanément indisponible. Réessayez dans un instant."
    )
