from app.services import student_weakness_model_service as service


def main() -> None:
    expected = {
        "Question de grammaire et conjugaison": "Langue",
        "Identifier la métaphore dans cet extrait": "Figures de style",
        "Rédiger un texte argumentatif": "Production écrite",
        "Respecter la consigne et gérer le temps": "Méthodologie",
        "Suivre les consignes et gérer le temps imparti": "Méthodologie",
        "Organisation du temps et respect de la consigne": "Méthodologie",
        "Quel est le personnage principal ?": "Compréhension",
    }
    for text, label in expected.items():
        actual = service.canonical_competence(text)
        if actual != label:
            raise SystemExit(f"Mapping incorrect: {text!r} -> {actual!r}, attendu {label!r}")

    if service.canonical_competence("question sans catégorie explicite") is not None:
        raise SystemExit("Une catégorie inconnue ne doit plus devenir Compréhension.")

    records = service.record_list([{"competence": "Langue"}, {"competence": "Méthodologie"}])
    if len(records) != 2:
        raise SystemExit("La lecture multi-réponses ne fonctionne pas.")

    debug = service.get_model_debug()
    if not debug.get("loaded"):
        raise SystemExit("Le modèle student_weakness_predictor_v1 n'est pas chargé.")

    print("Mapping compétences: OK")
    print("Lecture multi-réponses: OK")
    print("Inconnus non forcés en Compréhension: OK")
    print("Modèle chargé:", debug.get("version"))
    print("Collector:", debug.get("collector_version"))
    print("VÉRIFICATION V1.2 RÉUSSIE")


if __name__ == "__main__":
    main()
