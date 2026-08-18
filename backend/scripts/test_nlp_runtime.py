# EDUMENTOR_V22_PATH_FIX
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
from app.nlp_runtime.services.adaptation import adapt_text
from app.nlp_runtime.services.content import predict_content_type
from app.nlp_runtime.services.figures_exam import (
    analyze_figure,
    classify_exam_competence,
)
from app.nlp_runtime.services.level import predict_level
from app.nlp_runtime.services.qa import generate_pair
from app.nlp_runtime.services.registry import get_registry


registry = get_registry()

checks = {
    "status": registry.status(),
    "level": predict_level(
        registry,
        "Analysez la portÃ©e symbolique de la cellule.",
    ),
    "content_type": predict_content_type(
        registry,
        instruction="Pose une question sur les faits du chapitre.",
        ui_section="entrainement",
        pair_role="question",
        competence="comprehension",
    ),
    "adaptation": adapt_text(
        registry,
        source_text=(
            "Le condamnÃ© rÃ©flÃ©chit aux consÃ©quences sociales "
            "et morales de lâ€™exÃ©cution."
        ),
        source_level="intermediaire",
        target_level="avance",
        content_type="explication_detaillee",
        unit_title="La peine de mort",
        adaptation_id="smoke-v22",
    ),
    "qa": generate_pair(
        registry,
        unit_id="LBM_CH01",
        task="comprehension",
        level="debutant",
    ),
    "figure": analyze_figure(
        registry,
        "La nuit murmure Ã  lâ€™oreille dâ€™Antigone.",
    ),
    "exam": classify_exam_competence(
        registry,
        "Quelle valeur symbolique possÃ¨de cette cellule ?",
    ),
}

assert checks["status"]["holdout_loaded"] is False
assert checks["level"]["predicted_level"]
assert checks["content_type"]["content_type"]
assert checks["adaptation"]["adapted_text"]
assert checks["qa"]["question"] and checks["qa"]["correction"]
assert checks["figure"]["figure_type"] == "personnification"
assert checks["exam"]["competence"] == "interpretation"

for name, result in checks.items():
    print(name, "=>", result)

print("NLP RUNTIME V22 OK")