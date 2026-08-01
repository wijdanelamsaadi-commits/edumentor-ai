from __future__ import annotations

from app.models.persistence import RemediationPlan, StudyPath


def explain_study_path_update(plan: RemediationPlan, path: StudyPath | None = None) -> dict:
    weak_items = [item for item in plan.items if not item.completed]
    return {
        "generation_method": "backend_validated_ai_recommendation_ready",
        "reason": "Le backend conserve l'orchestration et peut intégrer une proposition IA validée sans accepter d'ID inexistant.",
        "weak_targets": [{"chapter_id": item.chapter_id, "skill_id": item.skill_id, "reason": item.reason} for item in weak_items],
        "current_path_id": path.id if path else None,
    }

