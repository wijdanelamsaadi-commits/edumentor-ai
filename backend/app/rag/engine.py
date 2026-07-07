def rag_status() -> dict:
    return {
        "enabled": True,
        "mode": "rag_semantic",
        "planned_steps": [
            "Brancher un fournisseur LLM",
            "Generer des reponses contextualisees avec citations",
        ],
    }
