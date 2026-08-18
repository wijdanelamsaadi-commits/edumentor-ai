from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import regional_auto_grader_service as grader


def question(qid, text, points, qtype, expected=None, explanation="", rubric=None, correct_answer="", choices=None):
    metadata = {
        "question_type": qtype,
        "expected_elements": expected or [],
        "rubric": rubric or [],
        "requires_teacher_validation": False,
        "scoring_mode": "automatic_hybrid",
    }
    return SimpleNamespace(
        id=qid,
        question=text,
        points=points,
        correct_answer=correct_answer,
        explanation=explanation,
        choices=choices or [],
        adaptation_reason=json.dumps(metadata, ensure_ascii=False),
    )


def main() -> int:
    q1 = question(1, "Date de publication ?", 0.25, "response_short", ["1954"], correct_answer="1954")
    assert grader.grade_closed_answer(q1, "1954")["points_awarded"] == 0.25
    assert grader.grade_closed_answer(q1, "1945")["points_awarded"] == 0

    q2 = question(
        2,
        "La difficulté de Sidi Mohamed à se réveiller est-elle due au fait qu’il est rêveur ? Justifiez.",
        1,
        "response_long",
        ["prise de position", "justification liée au réveil à trois heures"],
        "Exemple attendu : non, se réveiller à trois heures est difficile pour tout enfant.",
    )
    good = "Non, je ne suis pas d’accord, car il est trois heures du matin et il est normal qu’un enfant ait encore sommeil."
    good_score = grader.grade_open_fallback(q2, good)["points_awarded"]
    short_score = grader.grade_open_fallback(q2, "oui")["points_awarded"]
    assert good_score >= 0.8, good_score
    assert short_score < 0.5, short_score

    q3 = question(
        3,
        "Les gens qui se lèvent tard sont-ils paresseux ? Rédigez un texte argumentatif.",
        10,
        "production_ecrite",
        ["Respect de la consigne", "Texte argumentatif cohérent et bien structuré", "Langue correcte"],
        rubric=[
            {"criterion": "Respect de la consigne", "points": 1},
            {"criterion": "Texte argumentatif cohérent et bien structuré", "points": 4},
            {"criterion": "Correction de la langue", "points": 5},
        ],
    )
    essay = (
        "Je ne partage pas cette opinion, car se lever tard ne signifie pas forcément être paresseux. "
        "Certaines personnes travaillent tard et ont besoin de dormir le matin. Par exemple, un étudiant peut réviser "
        "jusqu’à une heure tardive et obtenir de bons résultats. De plus, la réussite dépend du sérieux, de l’organisation "
        "et des efforts. Une personne peut se lever tôt sans être productive, alors qu’une autre peut commencer plus tard "
        "et accomplir efficacement ses tâches. Cependant, se lever très tard sans raison peut entraîner une mauvaise "
        "organisation. En conclusion, l’heure du réveil ne détermine pas la réussite ; la discipline et le travail régulier comptent davantage."
    )
    essay_fallback = grader.grade_open_fallback(q3, essay)
    essay_result = grader._calibrate_open_result(grader._open_item(q3, essay), None, essay_fallback)
    essay_score = essay_result["points_awarded"]
    assert 7.0 <= essay_score <= 9.5, essay_score
    assert abs(round(essay_score * 4) - essay_score * 4) < 1e-9, essay_score

    print("Questions fermées: OK")
    print(f"Réponse justifiée: {good_score}/1")
    print(f"Réponse non justifiée: {short_score}/1")
    print(f"Production écrite: {essay_score}/10")
    print(f"Version: {grader.AUTO_GRADER_VERSION}")
    print("VERIFICATION AUTO-CORRECTEUR V1.2 REUSSIE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
