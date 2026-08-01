from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import HTTPException

from app.schemas.ai_generation import AdaptiveChapterVariant, AdaptiveChapterVariantContent, AdaptiveChapterVariantSet, GeneratedQuestion, PracticeQuestion
from app.services import adaptive_diagnostic_service, ai_assessment_generation_service, ai_course_generation_service, automatic_course_generation_service, course_service, rich_course_content_service
from app.services.adaptive_generation_benchmark_service import build_metrics, recommended_solution
from app.services.ai.ai_provider import AIProviderError, AIResponse
from app.services.ai.duplicate_detection_service import is_duplicate, max_similarity, token_similarity
from app.services.ai.quality_validation_service import level_variant_difference, score_course_chapter


def test_deterministic_chapter_variant_has_required_sections():
    variant = ai_course_generation_service.deterministic_chapter_variant(
        "Compréhension du texte",
        "debutant",
        [{"id": "src-1", "text": "Le passage explique le rôle du narrateur et les indices explicites du texte."}],
    )

    payload = variant.model_dump()
    quality = score_course_chapter(payload, {"src-1"})

    assert variant.level == "debutant"
    assert variant.introduction
    assert len(variant.detailed_explanations) >= 3
    assert variant.knowledge_check
    assert quality["quality_score"] >= 0.75


def test_adaptive_chapter_variant_schema_is_strict():
    payload = {
        "level": "intermediaire",
        "chapter_source_id": "chapter_1",
        "title": "Antigone",
        "summary": "Resume adapte.",
        "explanation": "Explication fondee sur la source.",
        "key_points": ["Point cle"],
        "vocabulary": [{"term": "Conflit", "definition": "Opposition entre deux forces."}],
        "guided_example": {"title": "Exemple", "content": "Analyse guidee."},
        "learning_support": ["Relire la source"],
        "practice_question": {
            "question": "Quelle idee faut-il justifier ?",
            "expected_answer": "Une idee presente dans la source.",
            "explanation": "La justification reste liee au cours.",
        },
        "source_block_ids": ["src-1"],
        "generation_method": "ai_generated",
        "model": "mock-model",
        "generated_at": "2026-07-26T00:00:00",
    }

    variant = AdaptiveChapterVariant.model_validate(payload)

    assert variant.level == "intermediaire"
    assert variant.source_block_ids == ["src-1"]


def test_deterministic_adaptive_variant_uses_source_ids_and_level():
    variant = ai_course_generation_service.deterministic_adaptive_chapter_variant(
        chapter_source_id="chapter_2",
        chapter_title="Antigone",
        level="avance",
        sources=[{"id": "src-antigone", "text": "Antigone refuse l'ordre de Creon dans la source du professeur."}],
    )

    assert variant.level == "avance"
    assert variant.chapter_source_id == "chapter_2"
    assert variant.source_block_ids == ["src-antigone"]
    assert variant.generation_method == "deterministic_fallback"


def test_adaptive_visible_blocks_are_different_for_each_level():
    sources = [{"id": "src-1", "text": "Antigone refuse l'ordre de Creon et defend son devoir envers son frere."}]
    beginner = ai_course_generation_service.deterministic_adaptive_chapter_variant(
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        level="debutant",
        sources=sources,
    )
    intermediate = ai_course_generation_service.deterministic_adaptive_chapter_variant(
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        level="intermediaire",
        sources=sources,
    )
    advanced = ai_course_generation_service.deterministic_adaptive_chapter_variant(
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        level="avance",
        sources=sources,
    )

    beginner_text = " ".join(str(block.get("content", "")) for block in beginner.model_dump()["blocks"])
    intermediate_text = " ".join(str(block.get("content", "")) for block in intermediate.model_dump()["blocks"])
    advanced_text = " ".join(str(block.get("content", "")) for block in advanced.model_dump()["blocks"])

    assert beginner_text != intermediate_text
    assert intermediate_text != advanced_text
    assert "Etape 1" in beginner_text
    assert "justification courte" in intermediate_text
    assert "argumentation synthetique" in advanced_text


def test_adaptive_blocks_keep_traceability_metadata():
    variant = ai_course_generation_service.deterministic_adaptive_chapter_variant(
        chapter_source_id="chapter_2",
        chapter_title="Analyse",
        level="intermediaire",
        sources=[{"id": "src-2", "type": "paragraph", "source_hash": "abc", "text": "Source du professeur."}],
    )

    for block in variant.model_dump()["blocks"]:
        assert block["source_block_id"]
        assert block["source_chapter_id"] == "chapter_2"
        assert block["original_block_type"]
        assert block["level"] == "intermediaire"
        assert block["generation_method"] == "deterministic_fallback"


def test_official_source_is_preserved_as_official_block():
    variant = ai_course_generation_service.deterministic_adaptive_chapter_variant(
        chapter_source_id="chapter_exam",
        chapter_title="Examen regional",
        level="avance",
        sources=[
            {
                "id": "official-1",
                "type": "quote",
                "section": "regional_exams",
                "title": "Session officielle",
                "text": "Texte officiel de l'examen regional - Session 2025.",
                "source_hash": "official-hash",
            }
        ],
    )

    official_blocks = [block for block in variant.model_dump()["blocks"] if block["generation_method"] == "official_source"]

    assert len(official_blocks) == 1
    assert official_blocks[0]["content"] == "Texte officiel de l'examen regional - Session 2025."


def test_compact_variant_sources_exclude_heavy_and_official_payloads():
    settings = {
        "ai_variant_source_max_chars": 8000,
        "ai_variant_max_input_tokens": 2200,
    }
    sources = [
        {"id": "main", "type": "paragraph", "section": "analysis", "text": "Antigone refuse l'ordre de Creon."},
        {"id": "exam", "type": "regional_exam", "section": "regional_exams", "text": "Sujet officiel"},
        {"id": "pdf", "type": "pdf", "text": "http://example.test/support.pdf"},
        {"id": "visual", "type": "visual", "text": "graph TD; A-->B"},
        {"id": "qcm", "type": "qcm", "text": "A/B/C/D", "metadata": {"correct_answer": "A"}},
    ]

    compact = ai_course_generation_service.prepare_compact_variant_sources(sources, settings)

    assert [source["id"] for source in compact] == ["main"]
    assert "Sujet officiel" not in json.dumps(compact, ensure_ascii=False)


def _words(prefix: str, count: int) -> str:
    clean_prefix = prefix.replace("_", "")
    return " ".join(f"{clean_prefix}{index}" for index in range(1, count + 1))


def _level_text(level: str, section: str, count: int) -> str:
    profiles = {
        "debutant": "simple repere ordre comprendre enfant aide image souvenir maison",
        "intermediaire": "analyse narrateur focalisation registre symbole justification theme relation",
        "avance": "interpretation structure narrative portee symbolique argumentation nuance critique",
    }
    base = profiles.get(level, profiles["intermediaire"])
    return f"{section} {level}. {base}. {_words(f'{section}_{level}_', count)}"


def _minimal_variant(level: str, text: str | None = None) -> dict:
    return {
        "level": level,
        "chapter_source_id": "wrong-source",
        "title": f"Antigone {level}",
        "summary": text or _level_text(level, "summary", 170),
        "explanation": _level_text(level, "explanation", 360),
        "key_points": [
            f"Point {index} {level}: {_level_text(level, f'point{index}', 10)}"
            for index in range(1, 7)
        ],
        "vocabulary": [
            {"term": f"Notion {index}", "definition": f"Definition {level} {index}: {_level_text(level, f'definition{index}', 8)}"}
            for index in range(1, 7)
        ],
        "guided_example": {"title": "Exemple guidé", "content": _level_text(level, "guided_example", 220)},
        "learning_support": [
            _level_text(level, "support_methode", 45),
            _level_text(level, "support_question", 45),
            _level_text(level, "support_piege", 45),
        ],
        "practice_question": {
            "question": f"Question {level}: {_level_text(level, 'question', 28)} ?",
            "expected_answer": _level_text(level, "expected_answer", 45),
            "explanation": _level_text(level, "practice_explanation", 55),
        },
        "source_block_ids": ["src-1"],
        "generation_method": "ai_generated",
        "model": "mock-model",
        "generated_at": "2026-07-27T00:00:00",
        "blocks": [],
    }


def _minimal_content(level: str) -> dict:
    return {
        "summary": _level_text(level, "summary", 170),
        "explanation": _level_text(level, "explanation", 360),
        "key_points": [
            {"title": f"Point {index} {level}", "content": _level_text(level, f"point{index}", 10)}
            for index in range(1, 7)
        ],
        "vocabulary": [
            {"term": f"Notion {index}", "definition": _level_text(level, f"definition{index}", 8)}
            for index in range(1, 7)
        ],
        "guided_example": {
            "title": "Exemple guidé",
            "instruction": _level_text(level, "guided_instruction", 20),
            "content": _level_text(level, "guided_example", 190),
            "steps": [_level_text(level, "step_one", 18), _level_text(level, "step_two", 18)],
            "answer": _level_text(level, "guided_answer", 45),
        },
        "learning_support": {
            "method": _level_text(level, "support_method", 45),
            "steps": [_level_text(level, "support_step", 35)],
            "pitfalls": [_level_text(level, "support_pitfall", 35)],
            "memory_tip": _level_text(level, "support_memory", 35),
        },
        "practice_question": {
            "question": f"Question {level}: {_level_text(level, 'question', 28)} ?",
            "instruction": _level_text(level, "practice_instruction", 20),
            "difficulty": level,
            "expected_elements": [_level_text(level, "expected_element", 25), _level_text(level, "expected_element_two", 25)],
            "explanation": _level_text(level, "practice_explanation", 55),
        },
        "blocks": [],
    }


def _minimal_variant_set_payload(variants_format: str = "dict") -> dict:
    variants = {
        "debutant": _minimal_variant("debutant"),
        "intermediaire": _minimal_variant("intermediaire"),
        "avance": _minimal_variant("avance"),
    }
    if variants_format == "list":
        variants = list(variants.values())
    return {
        "chapter_id": "197",
        "chapter_source_id": "197",
        "variants": variants,
    }


def test_normalize_variant_payload_keeps_dict_shape_and_forces_source_id():
    normalized, metadata = ai_course_generation_service.normalize_adaptive_variant_payload(
        _minimal_variant_set_payload("dict"),
        expected_chapter_source_id="chapter_1",
    )

    assert metadata["original_variants_format"] == "dict"
    assert metadata["raw_structure_normalized"] is True
    assert normalized["chapter_source_id"] == "chapter_1"
    assert "chapter_id" not in normalized
    assert set(normalized["variants"]) == {"debutant", "intermediaire", "avance"}
    assert all(variant["chapter_source_id"] == "chapter_1" for variant in normalized["variants"].values())


def test_normalize_variant_payload_converts_list_to_dict():
    normalized, metadata = ai_course_generation_service.normalize_adaptive_variant_payload(
        _minimal_variant_set_payload("list"),
        expected_chapter_source_id="chapter_1",
    )

    assert metadata["original_variants_format"] == "list"
    assert isinstance(normalized["variants"], dict)
    assert AdaptiveChapterVariantSet.model_validate(normalized)


def test_normalize_variant_payload_normalizes_level_aliases_and_preserves_content():
    payload = {
        "chapter_id": "197",
        "variants": [
            _minimal_variant("Débutant", text="Texte pédagogique inchangé 1."),
            _minimal_variant("Intermediate", text="Texte pédagogique inchangé 2."),
            _minimal_variant("Advanced", text="Texte pédagogique inchangé 3."),
        ],
    }

    normalized, _metadata = ai_course_generation_service.normalize_adaptive_variant_payload(payload, "chapter_1")

    assert normalized["variants"]["debutant"]["level"] == "debutant"
    assert normalized["variants"]["intermediaire"]["level"] == "intermediaire"
    assert normalized["variants"]["avance"]["level"] == "avance"
    assert normalized["variants"]["debutant"]["summary"] == "Texte pédagogique inchangé 1."


def test_normalize_variant_payload_rejects_missing_variant():
    payload = _minimal_variant_set_payload("dict")
    payload["variants"].pop("avance")

    try:
        ai_course_generation_service.normalize_adaptive_variant_payload(payload, "chapter_1")
    except ValueError as exc:
        assert "missing levels" in str(exc)
    else:
        raise AssertionError("missing variant should be rejected")


def test_normalize_variant_payload_rejects_unknown_level():
    payload = {
        "variants": [
            _minimal_variant("debutant"),
            _minimal_variant("intermediaire"),
            _minimal_variant("expert"),
        ]
    }

    try:
        ai_course_generation_service.normalize_adaptive_variant_payload(payload, "chapter_1")
    except ValueError as exc:
        assert "unknown" in str(exc) or "missing" in str(exc)
    else:
        raise AssertionError("unknown variant level should be rejected")


def test_single_level_content_schema_has_no_missing_levels_error():
    content = AdaptiveChapterVariantContent.model_validate(_minimal_content("debutant"))

    assert content.summary
    assert content.practice_question.instruction


def test_practice_question_instruction_is_explicitly_accepted():
    question = PracticeQuestion.model_validate(
        {
            "question": "Analysez le passage en respectant la consigne.",
            "instruction": "Repondez en deux etapes.",
            "difficulty": "intermediaire",
            "expected_elements": ["idee principale", "justification"],
            "explanation": "La reponse doit relier l'idee a un indice.",
        }
    )

    assert question.instruction == "Repondez en deux etapes."
    assert "idee principale" in question.expected_answer


def test_practice_question_unknown_extra_is_rejected():
    try:
        PracticeQuestion.model_validate(
            {
                "question": "Question ?",
                "instruction": "Consigne",
                "difficulty": "debutant",
                "expected_elements": ["element"],
                "explanation": "Explication",
                "unknown": "forbidden",
            }
        )
    except Exception as exc:
        assert "Extra inputs are not permitted" in str(exc)
    else:
        raise AssertionError("unknown practice question fields should be rejected")


def test_groq_content_normalization_extracts_summary_and_explanation_text():
    payload = _minimal_content("debutant")
    payload["summary"] = {"text": payload["summary"], "length": 120}
    payload["explanation"] = {"text": payload["explanation"], "length": 180}

    normalized = ai_course_generation_service.normalize_adaptive_content_payload(payload)
    content = AdaptiveChapterVariantContent.model_validate(normalized)

    assert isinstance(content.summary, str)
    assert isinstance(content.explanation, str)
    assert "length" not in content.summary


def test_groq_content_normalization_converts_string_lists():
    payload = _minimal_content("intermediaire")
    payload["learning_support"]["pitfalls"] = "Ne pas confondre résumé et analyse."
    payload["practice_question"]["expected_elements"] = "Une idée principale justifiée."

    normalized = ai_course_generation_service.normalize_adaptive_content_payload(payload)
    content = AdaptiveChapterVariantContent.model_validate(normalized)

    assert content.learning_support.pitfalls == ["Ne pas confondre résumé et analyse."]
    assert content.practice_question.expected_elements == ["Une idée principale justifiée."]


def test_groq_content_normalization_converts_guided_step_objects():
    payload = _minimal_content("avance")
    payload["guided_example"]["steps"] = [{"step": "Repérer l'idée."}, {"step": "Justifier avec un indice."}]

    normalized = ai_course_generation_service.normalize_adaptive_content_payload(payload)
    content = AdaptiveChapterVariantContent.model_validate(normalized)

    assert content.guided_example.steps == ["Repérer l'idée.", "Justifier avec un indice."]


def test_groq_content_normalization_maps_recognizable_blocks_and_removes_server_keys():
    payload = _minimal_content("intermediaire")
    payload["blocks"] = [
        {
            "question": "Quelle idée faut-il analyser ?",
            "title": "Entraînement",
            "source_block_id": "src-1",
            "source_chapter_id": "chapter_1",
            "level": "intermediaire",
            "generation_method": "ai_generated",
        },
        {"type": "resume", "title": "Résumé", "content": "Texte de résumé."},
    ]

    normalized = ai_course_generation_service.normalize_adaptive_content_payload(payload)
    content = AdaptiveChapterVariantContent.model_validate(normalized)

    assert content.blocks[0].type == "exercise"
    assert content.blocks[0].content == "Quelle idée faut-il analyser ?"
    assert content.blocks[1].type == "summary"
    assert not hasattr(content.blocks[0], "source_block_id")


def test_groq_content_normalization_does_not_allow_unknown_block_extra():
    payload = _minimal_content("debutant")
    payload["blocks"] = [{"type": "summary", "content": "Résumé.", "unknown": "forbidden"}]
    normalized = ai_course_generation_service.normalize_adaptive_content_payload(payload)

    try:
        AdaptiveChapterVariantContent.model_validate(normalized)
    except Exception as exc:
        assert "Extra inputs are not permitted" in str(exc)
    else:
        raise AssertionError("unknown block extra should still be rejected")


class FakeVariantSetProvider:
    def __init__(self, failures: list[Exception] | None = None, payloads: list[dict] | None = None):
        self.failures = failures or []
        self.payloads = payloads or []
        self.requests = []

    def generate_structured(self, request):
        self.requests.append(request)
        if self.failures:
            raise self.failures.pop(0)
        level = (request.metadata or {}).get("level") or "intermediaire"
        payload = self.payloads.pop(0) if self.payloads else _minimal_content(level)
        return AIResponse(
            text=json.dumps(payload),
            provider="groq",
            model_name="mock-model",
            usage={"prompt_tokens": 120, "completion_tokens": 220},
        )

    def get_usage_metadata(self, response):
        return {"model": response.model_name}


def _split_payloads(*levels: str) -> list[dict]:
    payloads: list[dict] = []
    for level in levels:
        content = _minimal_content(level)
        payloads.extend([content, content])
    return payloads


def _variant_settings():
    return {
        "ai_content_generation_enabled": True,
        "ai_variant_source_max_chars": 8000,
        "ai_variant_max_input_tokens": 2200,
        "ai_variant_max_output_tokens": 1800,
        "ai_groq_tpm_budget": 5500,
        "ai_variant_timeout_seconds": 20,
        "ai_variant_model": "mock-model",
        "ai_model": "mock-model",
        "ai_variant_min_interval_seconds": 0,
    }


def test_groq_variant_generation_uses_two_requests_per_level(monkeypatch):
    provider = FakeVariantSetProvider()
    monkeypatch.setattr(ai_course_generation_service, "get_settings", _variant_settings)
    monkeypatch.setattr(ai_course_generation_service, "get_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_course_generation_service, "record_generation", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_course_generation_service, "wait_for_variant_rate_limit", lambda _seconds: None)

    variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
        None,
        course_id=23,
        chapter_id=96,
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        subject="Francais",
        sources=[{"id": "src-1", "type": "paragraph", "text": "Antigone refuse l'ordre de Creon."}],
        user_id=1,
    )

    assert len(provider.requests) == 6
    assert set(variants) == {"debutant", "intermediaire", "avance"}
    assert all(variant.generation_method == "ai_generated" for variant in variants.values())
    assert metadata["debutant"]["validation_status"] == "validated"
    assert metadata["debutant"]["repair_attempted"] is False
    assert metadata["debutant"]["attempts"] == 2
    assert metadata["debutant"]["final_http_status"] == 200
    phases = [json.loads(request.user_prompt)["phase"] for request in provider.requests]
    assert phases == ["main_content", "pedagogical_support"] * 3
    assert all(json.loads(request.user_prompt)["level"] in {"debutant", "intermediaire", "avance"} for request in provider.requests)


def test_single_level_generation_injects_server_metadata(monkeypatch):
    provider = FakeVariantSetProvider(payloads=_split_payloads("debutant", "intermediaire", "avance"))
    monkeypatch.setattr(ai_course_generation_service, "get_settings", _variant_settings)
    monkeypatch.setattr(ai_course_generation_service, "get_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_course_generation_service, "record_generation", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_course_generation_service, "wait_for_variant_rate_limit", lambda _seconds: None)

    variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
        None,
        course_id=23,
        chapter_id=197,
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        subject="Francais",
        sources=[{"id": "src-1", "type": "paragraph", "text": "Antigone refuse l'ordre de Creon."}],
        user_id=1,
    )

    assert len(provider.requests) == 6
    assert variants["intermediaire"].chapter_source_id == "chapter_1"
    assert variants["intermediaire"].title == "Antigone"
    assert variants["intermediaire"].generation_method == "ai_generated"
    assert variants["intermediaire"].generated_at
    assert variants["intermediaire"].source_block_ids == ["src-1"]
    assert metadata["intermediaire"]["generation_method"] == "ai_generated"


def test_groq_variant_generation_repairs_after_validation_error(monkeypatch):
    invalid_payload = _minimal_content("debutant")
    invalid_payload["guided_example"] = {"title": "Exemple", "content": "Exemple"}
    provider = FakeVariantSetProvider(payloads=[
        _minimal_content("debutant"),
        invalid_payload,
        _minimal_content("debutant"),
        *_split_payloads("intermediaire", "avance"),
    ])
    monkeypatch.setattr(ai_course_generation_service, "get_settings", _variant_settings)
    monkeypatch.setattr(ai_course_generation_service, "get_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_course_generation_service, "record_generation", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_course_generation_service, "wait_for_variant_rate_limit", lambda _seconds: None)

    variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
        None,
        course_id=23,
        chapter_id=197,
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        subject="Francais",
        sources=[{"id": "src-1", "type": "paragraph", "text": "Antigone refuse l'ordre de Creon."}],
        user_id=1,
    )

    assert len(provider.requests) == 7
    assert variants["debutant"].generation_method == "ai_generated"
    assert metadata["debutant"]["validation_status"] == "validated_after_repair"
    assert metadata["debutant"]["repair_attempted"] is True
    assert metadata["debutant"]["attempts"] == 3


def test_adaptive_variant_quality_rejects_short_summary_and_explanation():
    payload = _minimal_variant_set_payload("dict")
    payload["variants"]["intermediaire"]["summary"] = "Résumé adapté."
    payload["variants"]["intermediaire"]["explanation"] = "Explication trop courte."
    payload, _metadata = ai_course_generation_service.normalize_adaptive_variant_payload(payload, "chapter_1")
    model = AdaptiveChapterVariantSet.model_validate(payload)

    try:
        ai_course_generation_service.validate_adaptive_variant_set_quality(model)
    except ai_course_generation_service.AdaptiveVariantQualityError as exc:
        assert "intermediaire" in exc.invalid_levels
        assert "summary too short" in str(exc)
        assert "explanation too short" in str(exc)
    else:
        raise AssertionError("short pedagogical content should be rejected")


def test_adaptive_variant_quality_rejects_generic_learning_support():
    payload = _minimal_variant_set_payload("dict")
    payload["variants"]["debutant"]["learning_support"] = ["Aide"]
    payload, _metadata = ai_course_generation_service.normalize_adaptive_variant_payload(payload, "chapter_1")
    model = AdaptiveChapterVariantSet.model_validate(payload)

    try:
        ai_course_generation_service.validate_adaptive_variant_set_quality(model)
    except ai_course_generation_service.AdaptiveVariantQualityError as exc:
        assert "debutant" in exc.invalid_levels
        assert "learning_support" in str(exc)
    else:
        raise AssertionError("generic learning support should be rejected")


def test_adaptive_variant_quality_requires_complete_guided_example():
    payload = _minimal_variant_set_payload("dict")
    payload["variants"]["avance"]["guided_example"] = {"title": "Exemple", "content": "Exemple"}
    payload, _metadata = ai_course_generation_service.normalize_adaptive_variant_payload(payload, "chapter_1")
    model = AdaptiveChapterVariantSet.model_validate(payload)

    try:
        ai_course_generation_service.validate_adaptive_variant_set_quality(model)
    except ai_course_generation_service.AdaptiveVariantQualityError as exc:
        assert "avance" in exc.invalid_levels
        assert "guided_example incomplete" in str(exc)
    else:
        raise AssertionError("incomplete guided example should be rejected")


def test_adaptive_variant_quality_detects_similar_levels():
    payload = _minimal_variant_set_payload("dict")
    shared = _minimal_variant("intermediaire")
    for level in ("debutant", "intermediaire", "avance"):
        clone = dict(shared)
        clone["level"] = level
        clone["chapter_source_id"] = "chapter_1"
        payload["variants"][level] = clone
    payload, _metadata = ai_course_generation_service.normalize_adaptive_variant_payload(payload, "chapter_1")
    model = AdaptiveChapterVariantSet.model_validate(payload)

    try:
        ai_course_generation_service.validate_adaptive_variant_set_quality(model)
    except ai_course_generation_service.AdaptiveVariantQualityError as exc:
        assert {"debutant", "intermediaire"}.issubset(exc.invalid_levels)
        assert "too similar" in str(exc)
    else:
        raise AssertionError("similar level variants should be rejected")


def test_similar_variant_payload_triggers_targeted_repair(monkeypatch):
    shared = _minimal_content("intermediaire")
    provider = FakeVariantSetProvider(payloads=[shared, shared, shared])
    monkeypatch.setattr(ai_course_generation_service, "get_settings", _variant_settings)
    monkeypatch.setattr(ai_course_generation_service, "get_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_course_generation_service, "record_generation", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_course_generation_service, "wait_for_variant_rate_limit", lambda _seconds: None)

    variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
        None,
        course_id=23,
        chapter_id=197,
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        subject="Francais",
        sources=[{"id": "src-1", "type": "paragraph", "text": "Antigone refuse l'ordre de Creon."}],
        user_id=1,
    )

    assert len(provider.requests) == 10
    assert json.loads(provider.requests[6].user_prompt)["validation_feedback"]
    assert variants["avance"].generation_method == "ai_generated"
    assert any(data["repair_attempted"] for data in metadata.values())


def test_disabled_generation_does_not_call_provider(monkeypatch):
    provider = FakeVariantSetProvider()

    def disabled_settings():
        values = _variant_settings()
        values["ai_content_generation_enabled"] = False
        return values

    monkeypatch.setattr(ai_course_generation_service, "get_settings", disabled_settings)
    monkeypatch.setattr(ai_course_generation_service, "get_ai_provider", lambda: provider)

    variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
        None,
        course_id=23,
        chapter_id=197,
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        subject="Francais",
        sources=[{"id": "src-1", "type": "paragraph", "text": "Antigone refuse l'ordre de Creon."}],
        user_id=1,
    )

    assert provider.requests == []
    assert all(variant.generation_method == "deterministic_fallback" for variant in variants.values())
    assert metadata["debutant"]["validation_status"] == "not_attempted"


def test_generation_and_schema_repair_use_same_rate_limiter(monkeypatch):
    invalid_payload = _minimal_content("debutant")
    invalid_payload["summary"] = 123
    provider = FakeVariantSetProvider(payloads=[
        invalid_payload,
        _minimal_content("debutant"),
        _minimal_content("debutant"),
        *_split_payloads("intermediaire", "avance"),
    ])
    waits = []
    monkeypatch.setattr(ai_course_generation_service, "get_settings", _variant_settings)
    monkeypatch.setattr(ai_course_generation_service, "get_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_course_generation_service, "record_generation", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_course_generation_service, "wait_for_variant_rate_limit", lambda seconds: waits.append(seconds))

    variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
        None,
        course_id=23,
        chapter_id=197,
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        subject="Francais",
        sources=[{"id": "src-1", "type": "paragraph", "text": "Antigone refuse l'ordre de Creon."}],
        user_id=1,
    )

    assert variants["debutant"].generation_method == "ai_generated"
    assert len(waits) == 7
    assert len(provider.requests) == 7
    assert metadata["debutant"]["repair_attempted"] is True


def test_groq_429_waits_and_retries(monkeypatch):
    provider = FakeVariantSetProvider([AIProviderError("Groq request failed: HTTP 429 TPM Limit. Please try again in 2s")])
    waits = []
    sleeps = []
    monkeypatch.setattr(ai_course_generation_service, "get_settings", _variant_settings)
    monkeypatch.setattr(ai_course_generation_service, "get_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_course_generation_service, "record_generation", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_course_generation_service, "wait_for_variant_rate_limit", lambda seconds: waits.append(seconds))
    monkeypatch.setattr(ai_course_generation_service.time, "sleep", lambda seconds: sleeps.append(seconds))

    variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
        None,
        course_id=23,
        chapter_id=197,
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        subject="Francais",
        sources=[{"id": "src-1", "type": "paragraph", "text": "Antigone refuse l'ordre de Creon."}],
        user_id=1,
    )

    assert variants["debutant"].generation_method == "ai_generated"
    assert len(provider.requests) == 7
    assert len(waits) == 7
    assert sleeps == [5.0]
    assert metadata["debutant"]["rate_limit_retry_count"] == 1
    assert metadata["debutant"]["attempts"] == 3
    assert metadata["debutant"]["final_http_status"] == 200


def test_groq_429_falls_back_after_retry_exhaustion(monkeypatch):
    provider = FakeVariantSetProvider([
        AIProviderError("Groq request failed: HTTP 429 TPM Limit. Please try again in 1s"),
        AIProviderError("Groq request failed: HTTP 429 TPM Limit. Please try again in 1s"),
        AIProviderError("Groq request failed: HTTP 429 TPM Limit. Please try again in 1s"),
        AIProviderError("Groq request failed: HTTP 429 TPM Limit. Please try again in 1s"),
    ])
    sleeps = []
    monkeypatch.setattr(ai_course_generation_service, "get_settings", _variant_settings)
    monkeypatch.setattr(ai_course_generation_service, "get_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_course_generation_service, "record_generation", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_course_generation_service, "wait_for_variant_rate_limit", lambda _seconds: None)
    monkeypatch.setattr(ai_course_generation_service.time, "sleep", lambda seconds: sleeps.append(seconds))

    variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
        None,
        course_id=23,
        chapter_id=197,
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        subject="Francais",
        sources=[{"id": "src-1", "type": "paragraph", "text": "Antigone refuse l'ordre de Creon."}],
        user_id=1,
    )

    assert len(provider.requests) == 8
    assert sleeps == [4.0, 4.0, 4.0]
    assert variants["debutant"].generation_method == "deterministic_fallback"
    assert variants["intermediaire"].generation_method == "ai_generated"
    assert variants["avance"].generation_method == "ai_generated"
    assert metadata["debutant"]["rate_limit_retry_count"] == 3
    assert metadata["debutant"]["attempts"] == 4
    assert metadata["debutant"]["final_http_status"] == 429


def test_groq_variant_generation_falls_back_after_failed_repair(monkeypatch):
    invalid_payload = {"summary": "trop court"}
    provider = FakeVariantSetProvider(payloads=[invalid_payload, invalid_payload, invalid_payload, invalid_payload])
    monkeypatch.setattr(ai_course_generation_service, "get_settings", _variant_settings)
    monkeypatch.setattr(ai_course_generation_service, "get_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_course_generation_service, "record_generation", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_course_generation_service, "wait_for_variant_rate_limit", lambda _seconds: None)

    variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
        None,
        course_id=23,
        chapter_id=197,
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        subject="Francais",
        sources=[{"id": "src-1", "type": "paragraph", "text": "Antigone refuse l'ordre de Creon."}],
        user_id=1,
    )

    assert len(provider.requests) == 8
    assert variants["debutant"].generation_method == "deterministic_fallback"
    assert variants["intermediaire"].generation_method == "ai_generated"
    assert variants["avance"].generation_method == "ai_generated"
    assert metadata["debutant"]["error"]


def test_groq_413_retries_with_reduced_payload(monkeypatch):
    provider = FakeVariantSetProvider([AIProviderError("Groq request failed: HTTP 413 TPM limit")])
    monkeypatch.setattr(ai_course_generation_service, "get_settings", _variant_settings)
    monkeypatch.setattr(ai_course_generation_service, "get_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_course_generation_service, "record_generation", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_course_generation_service, "wait_for_variant_rate_limit", lambda _seconds: None)
    long_text = "Antigone refuse l'ordre de Creon. " * 500

    variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
        None,
        course_id=23,
        chapter_id=96,
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        subject="Francais",
        sources=[{"id": "src-1", "type": "paragraph", "text": long_text}],
        user_id=1,
    )

    assert len(provider.requests) == 7
    assert len(provider.requests[1].user_prompt) < len(provider.requests[0].user_prompt)
    assert variants["debutant"].generation_method == "ai_generated"
    assert metadata["debutant"]["retry_reason"] == "http_413_payload_reduced"


def test_groq_413_second_failure_returns_deterministic_fallback(monkeypatch):
    provider = FakeVariantSetProvider([
        AIProviderError("Groq request failed: HTTP 413 TPM limit"),
        AIProviderError("Groq request failed: HTTP 413 TPM limit"),
    ])
    monkeypatch.setattr(ai_course_generation_service, "get_settings", _variant_settings)
    monkeypatch.setattr(ai_course_generation_service, "get_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_course_generation_service, "record_generation", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_course_generation_service, "wait_for_variant_rate_limit", lambda _seconds: None)

    variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
        None,
        course_id=23,
        chapter_id=96,
        chapter_source_id="chapter_1",
        chapter_title="Antigone",
        subject="Francais",
        sources=[{"id": "src-1", "type": "paragraph", "text": "Antigone refuse l'ordre de Creon."}],
        user_id=1,
    )

    assert len(provider.requests) == 6
    assert variants["debutant"].generation_method == "deterministic_fallback"
    assert variants["intermediaire"].generation_method == "ai_generated"
    assert variants["avance"].generation_method == "ai_generated"
    assert metadata["debutant"]["retry_reason"] == "http_413_payload_reduced"


def test_adaptive_content_normalization_accepts_equivalent_groq_shapes():
    payload = _minimal_content("intermediaire")
    payload["summary"] = {"text": payload["summary"], "length": 130}
    payload["explanation"] = {"text": payload["explanation"], "length": 230}
    payload["key_points"] = [
        "Antigone défend un devoir familial.",
        {"title": "Conflit", "content": "Le conflit oppose loi personnelle et autorité."},
    ]
    payload["vocabulary"] = {"tragédie": "Pièce marquée par un conflit grave."}
    payload["learning_support"]["pitfalls"] = "Ne pas confondre résumé et analyse."
    payload["practice_question"]["expected_elements"] = "Idée, justification, conclusion."
    payload["guided_example"]["steps"] = [{"step": "Lire la consigne."}, {"step": "Repérer l'indice."}]
    payload["blocks"] = [
        {"title": "Séquence 1", "text": "Une séquence claire issue du chapitre."},
        {"type": "paragraph", "title": "Analyse", "text": "Un contenu placé dans le champ text."},
        {"title": "Question", "question": "Pourquoi Antigone refuse-t-elle ?", "content": "Question guidée."},
        {"title": "Correction", "answer": "Elle agit par devoir.", "content": "Réponse attendue."},
    ]

    normalized = ai_course_generation_service.normalize_adaptive_content_payload(payload)
    content = AdaptiveChapterVariantContent.model_validate(normalized)

    assert isinstance(content.summary, str)
    assert content.key_points[0].title == "Point clé 1"
    assert content.vocabulary[0].term == "tragédie"
    assert content.learning_support.pitfalls == ["Ne pas confondre résumé et analyse."]
    assert content.practice_question.expected_elements == ["Idée, justification, conclusion."]
    assert content.guided_example.steps == ["Lire la consigne.", "Repérer l'indice."]
    assert content.blocks[0].type == "paragraph"
    assert content.blocks[0].content == "Une séquence claire issue du chapitre."
    assert content.blocks[1].content == "Un contenu placé dans le champ text."
    assert content.blocks[2].type == "exercise"
    assert content.blocks[3].type == "correction"


def test_benchmark_metrics_validate_json_sections_and_quality():
    content = _minimal_content("intermediaire")

    metric = build_metrics(
        solution="Groq",
        model="mock-model",
        execution_type="api",
        status="completed",
        duration_seconds=2.5,
        calls=2,
        http_statuses=[200, 200],
        json_valid=True,
        repairs=0,
        content=content,
        errors=[],
        resources={"ram_total_bytes": "16000000000"},
        cost="test",
        strengths=["rapide"],
        limits=["quota"],
    )

    assert metric["json_valid"] is True
    assert metric["has_five_sections"] is True
    assert metric["intermediate_level_respected"] is True
    assert metric["key_points_count"] == 6
    assert metric["vocabulary_count"] == 6
    assert metric["pedagogical_quality"]["type"] == "heuristique"


def test_benchmark_recommendation_is_inconclusive_without_completed_runs():
    recommendation, justification = recommended_solution([
        {"solution": "Groq", "status": "rate_limited", "pedagogical_quality": {"qualite_generale": 0}},
        {"solution": "Ollama local", "status": "not_available", "pedagogical_quality": {"qualite_generale": 0}},
    ])

    assert recommendation == "NOT_DETERMINED"
    assert "Aucune execution complete" in justification


def test_selected_course_variant_prefers_ai_chapter_over_newer_fallback():
    course = SimpleNamespace(
        chapters=[
            SimpleNamespace(id=197, position=1, structured_content=[{"source_chapter_id": "chapter_1"}]),
            SimpleNamespace(id=198, position=2, structured_content=[{"source_chapter_id": "chapter_2"}]),
        ]
    )
    newer_fallback = SimpleNamespace(
        structured_content=[
            {"chapter_source_id": "chapter_1", "generation_method": "deterministic_fallback", "summary": "fallback recent"},
            {"chapter_source_id": "chapter_2", "generation_method": "deterministic_fallback", "summary": "fallback chapter 2"},
        ]
    )
    older_ai = SimpleNamespace(
        structured_content=[
            {"chapter_source_id": "197", "generation_method": "ai_generated", "summary": "ai valid chapter 1"}
        ]
    )

    selected = course_service.select_best_variant_chapters(course, [newer_fallback, older_ai])

    assert selected[0]["summary"] == "ai valid chapter 1"
    assert selected[1]["summary"] == "fallback chapter 2"
    assert course_service.generation_method_for_selected_chapters(selected) == "mixed"


def test_generation_method_ignores_official_source_blocks():
    assert automatic_course_generation_service.generation_method_from_counts(3, 3) == "ai_generated"
    assert automatic_course_generation_service.generation_method_from_counts(3, 1) == "mixed"
    assert automatic_course_generation_service.generation_method_from_counts(3, 0) == "deterministic_fallback"


def test_course_23_regeneration_request_keeps_course_identity():
    class FakeDb:
        def __init__(self):
            self.commits = 0

        def commit(self):
            self.commits += 1

    class FakeBackgroundTasks:
        def __init__(self):
            self.tasks = []

        def add_task(self, fn, *args):
            self.tasks.append((fn, args))

    automatic_course_generation_service.AI_VARIANT_TASKS_IN_PROGRESS.discard(23)
    db = FakeDb()
    background_tasks = FakeBackgroundTasks()
    course = SimpleNamespace(id=23, information={}, chapters=[], subject=None, level="Adaptatif")
    actor = SimpleNamespace(id=5)

    result = automatic_course_generation_service.request_course_ai_variant_regeneration(
        db,
        course,
        actor,
        background_tasks,
    )

    assert result["course_id"] == 23
    assert result["ai_variants_status"] == "processing"
    assert course.id == 23
    assert course.information["ai_generation"]["generation_method"] == "processing"
    assert db.commits == 1
    assert background_tasks.tasks[0][0].__name__ == "run_existing_course_ai_variant_generation"
    assert background_tasks.tasks[0][1][0] == 23


def test_selected_course_variant_regeneration_targets_requested_positions_only():
    class FakeDb:
        def __init__(self):
            self.commits = 0

        def commit(self):
            self.commits += 1

    class FakeBackgroundTasks:
        def __init__(self):
            self.tasks = []

        def add_task(self, fn, *args):
            self.tasks.append((fn, args))

    chapters = [
        SimpleNamespace(id=197 + index, title=f"Chapitre {index + 1}", position=index + 1, active=True, structured_content=[{"source_chapter_id": f"chapter_{index + 1}"}], content="")
        for index in range(12)
    ]
    automatic_course_generation_service.AI_VARIANT_TASKS_IN_PROGRESS.clear()
    db = FakeDb()
    background_tasks = FakeBackgroundTasks()
    course = SimpleNamespace(id=23, information={}, chapters=chapters, subject=SimpleNamespace(name="Français"), level="Adaptatif")
    actor = SimpleNamespace(id=5)

    result = automatic_course_generation_service.request_selected_course_ai_variant_regeneration(
        db,
        course,
        actor,
        background_tasks,
        chapter_positions=[1, 3, 4, 5, 8, 9],
        levels=["debutant", "intermediaire", "avance"],
        replace_existing=True,
    )

    assert result["course_id"] == 23
    assert result["status"] == "processing"
    assert result["chapter_positions"] == [1, 3, 4, 5, 8, 9]
    assert len(result["source_hash"]) == 64
    assert background_tasks.tasks[0][0].__name__ == "run_selected_course_ai_variant_generation"
    assert background_tasks.tasks[0][1][0] == 23
    assert background_tasks.tasks[0][1][3] == [1, 3, 4, 5, 8, 9]


def test_source_hash_is_normalized_to_sha256():
    raw = "course_hash:chapters-1-3-4-5-8-9:2026-07-27T00:00:00"
    normalized = automatic_course_generation_service.normalize_source_hash(raw)
    already_valid = automatic_course_generation_service.normalize_source_hash(normalized.upper())

    assert len(normalized) == 64
    assert normalized == already_valid
    assert automatic_course_generation_service.normalize_source_hash("x" * 64) != "x" * 64


def test_course_variant_chapter_sources_are_normalized_from_database_ids():
    course = SimpleNamespace(
        chapters=[
            SimpleNamespace(id=197, position=1, structured_content=[{"source_chapter_id": "chapter_1"}]),
            SimpleNamespace(id=198, position=2, structured_content=[{"source_chapter_id": "chapter_2"}]),
        ],
    )
    variant_chapters = [
        {"chapter_source_id": "197", "generation_method": "ai_generated", "summary": "Debutant source"},
        {"chapter_source_id": "198", "generation_method": "deterministic_fallback", "summary": "Fallback"},
    ]

    normalized = course_service.normalize_variant_chapter_sources(course, variant_chapters)

    assert normalized[0]["chapter_source_id"] == "chapter_1"
    assert normalized[0]["source_chapter_id"] == "chapter_1"
    assert normalized[0]["course_chapter_id"] == 197
    assert normalized[1]["chapter_source_id"] == "chapter_2"
    assert normalized[1]["course_chapter_id"] == 198


def test_course_variant_normalization_preserves_ai_generated_content():
    course = SimpleNamespace(chapters=[SimpleNamespace(id=197, position=1, structured_content=[{"source_chapter_id": "chapter_1"}])])
    variant_chapters = [{
        "chapter_source_id": "197",
        "generation_method": "ai_generated",
        "summary": "Résumé débutant unique",
        "explanation": "Explication débutant unique",
        "guided_example": {"title": "Exemple débutant", "content": "Contenu exemple"},
        "practice_question": {"question": "Question débutant ?", "expected_answer": "Réponse", "explanation": "Correction"},
    }]

    normalized = course_service.normalize_variant_chapter_sources(course, variant_chapters)

    assert normalized[0]["summary"] == "Résumé débutant unique"
    assert normalized[0]["explanation"] == "Explication débutant unique"
    assert normalized[0]["guided_example"]["title"] == "Exemple débutant"
    assert normalized[0]["practice_question"]["question"] == "Question débutant ?"


def test_ai_variant_chapters_are_processed_sequentially(monkeypatch):
    calls = []

    class FakeDb:
        def scalar(self, *_args, **_kwargs):
            return None

        def add(self, *_args, **_kwargs):
            return None

        def flush(self):
            return None

    def fake_generate(_db, *, chapter_source_id, chapter_title, sources, **kwargs):
        calls.append(chapter_source_id)
        variants = {
            level: ai_course_generation_service.deterministic_adaptive_chapter_variant(
                chapter_source_id=chapter_source_id,
                chapter_title=chapter_title,
                level=level,
                sources=sources,
            )
            for level in ("debutant", "intermediaire", "avance")
        }
        for variant in variants.values():
            variant.generation_method = "ai_generated"
        return variants, {level: {"status": "ai_generated"} for level in variants}

    monkeypatch.setattr(ai_course_generation_service, "generate_three_level_adaptive_variants", fake_generate)
    course = SimpleNamespace(id=23, title="Course 23", information={}, professor_id=5)

    summary = automatic_course_generation_service.create_ai_variants_from_sources(
        FakeDb(),
        course,
        subject="Francais",
        chapter_sources=[
            {"chapter_source_id": "chapter_1", "chapter_title": "Chapitre 1", "sources": [{"id": "s1", "text": "A"}]},
            {"chapter_source_id": "chapter_2", "chapter_title": "Chapitre 2", "sources": [{"id": "s2", "text": "B"}]},
            {"chapter_source_id": "chapter_3", "chapter_title": "Chapitre 3", "sources": [{"id": "s3", "text": "C"}]},
        ],
        source_hash="hash",
        user_id=5,
    )

    assert calls == ["chapter_1", "chapter_2", "chapter_3"]
    assert summary["generation_method"] == "ai_generated"
    assert course.id == 23


def test_three_level_variants_are_not_simple_copies():
    variants = {
        level: ai_course_generation_service.deterministic_chapter_variant(
            "Figures de style",
            level,
            [{"id": f"src-{level}", "text": "La source présente l'antithèse, l'anaphore et leur effet dans un texte."}],
        ).model_dump()
        for level in ("debutant", "intermediaire", "avance")
    }

    diff = level_variant_difference(variants)

    assert diff["sufficiently_different"] is True


def test_rich_course_blocks_cover_regional_chapter_requirements():
    blocks = rich_course_content_service.build_detailed_chapter_blocks(
        course_title="Préparation au régional de français",
        chapter_title="Antigone",
        level="intermediaire",
        source_context={
            "facts": "Antigone refuse l'ordre de Créon et choisit d'accomplir son devoir envers Polynice.",
            "exercise": "Présentez l'opposition entre Antigone et Créon.",
            "solution": "Antigone défend son devoir moral ; Créon défend la loi de la cité.",
            "works": [{"title": "Antigone", "author": "Jean Anouilh", "genre": "tragédie moderne"}],
            "source_label": "chapter_3",
        },
    )
    block_types = {block["type"] for block in blocks}

    assert {"paragraph", "definition", "methodology", "warning", "key_points", "exercise", "correction", "summary", "mini_assessment"} <= block_types
    assert len([block for block in blocks if block["type"] == "exercise"]) >= 3
    assert len([block for block in blocks if block["type"] == "correction"]) >= 3
    assert rich_course_content_service.count_words(blocks) >= 800


def test_rich_course_variants_are_level_specific():
    source_context = {
        "facts": "La Boîte à merveilles traite de l'enfance et de la vie traditionnelle.",
        "exercise": "",
        "solution": "",
        "works": [{"title": "La Boîte à merveilles", "author": "Ahmed Sefrioui", "genre": "roman autobiographique"}],
        "source_label": "chapter_2",
    }
    beginner = rich_course_content_service.build_detailed_chapter_blocks(
        course_title="Préparation au régional de français",
        chapter_title="La Boîte à merveilles",
        level="debutant",
        source_context=source_context,
    )
    advanced = rich_course_content_service.build_detailed_chapter_blocks(
        course_title="Préparation au régional de français",
        chapter_title="La Boîte à merveilles",
        level="avance",
        source_context=source_context,
    )

    assert beginner != advanced
    assert "Débutant" in beginner[0]["content"]
    assert "Avancé" in advanced[0]["content"]


def test_duplicate_detection_rejects_close_question():
    original = "Quelle information explicite faut-il retenir dans ce chapitre ?"
    candidate = "Quelle information explicite doit-on retenir dans ce chapitre ?"

    assert token_similarity(original, candidate) > 0.6
    assert is_duplicate(candidate, [original], threshold=0.6)


def test_ai_assessment_generation_fallback_when_disabled():
    fallback = GeneratedQuestion(
        question_text="Quelle démarche reste fondée sur la source ?",
        choices=["Lire la source", "Inventer", "Ignorer", "Changer de cours"],
        correct_answer="Lire la source",
        explanation="La réponse doit rester vérifiable dans le support.",
        difficulty="debutant",
        target_level="debutant",
    )

    generated, metadata = ai_assessment_generation_service.generate_question(
        None,
        course_id=1,
        chapter_id=2,
        skill="Compréhension",
        level="debutant",
        difficulty="debutant",
        sources=[{"id": "src-1", "text": "Source courte"}],
        existing_questions=[],
        fallback=fallback,
    )

    assert generated.question_text == fallback.question_text
    assert metadata["status"] == "deterministic_fallback"


def test_adaptive_diagnostic_next_difficulty_and_estimate():
    assert adaptive_diagnostic_service.next_difficulty("debutant", True) == "intermediaire"
    assert adaptive_diagnostic_service.next_difficulty("avance", False) == "intermediaire"

    estimate = adaptive_diagnostic_service.estimate_level(
        [
            {"difficulty": "debutant", "correct": True},
            {"difficulty": "intermediaire", "correct": True},
            {"difficulty": "avance", "correct": False},
        ]
    )

    assert estimate["level"] == "intermediaire"
    assert 0 < estimate["confidence"] <= 1


def test_max_similarity_handles_empty_candidates():
    assert max_similarity("question", []) == 0.0


def test_phase10_v1_schema_still_accepts_existing_minimal_package():
    package = {
        "schema_version": "1.0",
        "course": {
            "title": "Preparation V1",
            "summary": "Resume V1.",
            "description": "Description V1.",
            "subject": "Francais",
            "education_level": "1ere annee Baccalaureat",
            "difficulty": "Adaptatif",
            "estimated_duration_hours": 8,
            "prerequisites": [],
        },
        "target": {
            "country": "Maroc",
            "cycle": "1ere_bac",
            "academic_year": "2026-2027",
            "region": "Toutes les regions",
            "stream": "Toutes filieres",
            "exam_type": "regional",
        },
        "works": [],
        "chapters": [
            {
                "id": "chapter_1",
                "title": "Chapitre V1",
                "order": 1,
                "objectives": ["Comprendre"],
                "skills": ["Comprehension"],
                "content_blocks": [{"type": "paragraph", "content": "Contenu V1."}],
                "latex_reference": "chapter_1",
            }
        ],
        "assessment_blueprint": {
            "questions_per_assessment": 10,
            "duration_minutes": 30,
            "passing_score": 70,
            "max_attempts": 2,
            "skills": ["Comprehension"],
            "levels": {
                "debutant": {"direct_questions_ratio": 0.7, "analysis_questions_ratio": 0.2, "production_questions_ratio": 0.1},
                "intermediaire": {"direct_questions_ratio": 0.4, "analysis_questions_ratio": 0.4, "production_questions_ratio": 0.2},
                "avance": {"direct_questions_ratio": 0.2, "analysis_questions_ratio": 0.4, "production_questions_ratio": 0.4},
            },
        },
    }

    parsed = automatic_course_generation_service.parse_package(json.dumps(package).encode("utf-8"))

    assert parsed.schema_version == "1.0"
    assert len(parsed.chapters) == 1


def phase10_v2_package(chapters_count: int = 6, visuals_count: int = 13, regional_items: list[dict] | None = None) -> bytes:
    chapters = []
    for index in range(1, chapters_count + 1):
        chapters.append(
            {
                "id": f"chapter_{index}",
                "title": f"Chapitre {index}",
                "order": index,
                "objectives": [f"Objectif {index}"],
                "skills": [f"Competence {index}"],
                "content_blocks": [{"type": "paragraph", "content": f"Contenu JSON du chapitre {index}."}],
                "latex_reference": f"chapter_{index}",
            }
        )
    visuals = [
        {
            "id": f"visual_{index}",
            "type": "mermaid" if index % 2 else "table",
            "title": f"Visuel {index}",
            "description": f"Specification visuelle {index}",
            "chapter_ref": f"chapter_{((index - 1) % chapters_count) + 1}",
            "status": "to_provide_or_generate",
        }
        for index in range(1, visuals_count + 1)
    ]
    package = {
        "schema_version": "2.0",
        "course": {
            "title": "Preparation regionale V2",
            "summary": "Resume du cours V2.",
            "description": "Description du cours V2.",
            "subject": "Francais",
            "education_level": "1ere annee Baccalaureat",
            "difficulty": "Adaptatif",
            "estimated_duration_hours": 12,
            "prerequisites": [],
        },
        "target": {
            "country": "Maroc",
            "cycle": "1ere_bac",
            "academic_year": "2026-2027",
            "region": "Toutes les regions",
            "stream": "Toutes filieres",
            "exam_type": "regional",
        },
        "works": [],
        "chapters": chapters,
        "visuals": visuals,
        "exam_training": {"objectives": ["Se preparer"], "methods": ["Lire la consigne"]},
        "content_quality_requirements": {
            "min_words_per_chapter": 800,
            "max_words_per_chapter": 1500,
            "required_sections": ["introduction", "exercices"],
        },
        "source_policy": {"allow_external_knowledge": False, "citation_required": True},
        "assets": {"generate_missing": True, "statuses": ["to_provide_or_generate"]},
        "ai_generation_rules": {"enabled": True, "provider": "groq", "retries": 2},
        "regional_exam_bank": {"items": regional_items or []},
        "latex_export": {"enabled": True, "include_visuals": True},
        "assessment_blueprint": {
            "questions_per_assessment": 10,
            "duration_minutes": 30,
            "passing_score": 70,
            "max_attempts": 2,
            "skills": ["Comprehension", "Analyse", "Langue"],
            "levels": {
                "debutant": {"direct_questions_ratio": 0.7, "analysis_questions_ratio": 0.2, "production_questions_ratio": 0.1},
                "intermediaire": {"direct_questions_ratio": 0.4, "analysis_questions_ratio": 0.4, "production_questions_ratio": 0.2},
                "avance": {"direct_questions_ratio": 0.2, "analysis_questions_ratio": 0.4, "production_questions_ratio": 0.4},
            },
        },
    }
    return json.dumps(package).encode("utf-8")


def phase10_latex(chapters_count: int = 6) -> str:
    return "\n".join(
        f"\\section{{Chapitre {index}}}\\label{{chapter_{index}}}\nTexte LaTeX du chapitre {index}."
        for index in range(1, chapters_count + 1)
    )


def test_phase10_v2_schema_is_accepted_and_counts_visuals_and_empty_exam_bank():
    package = automatic_course_generation_service.parse_package(phase10_v2_package())

    assert package.schema_version == "2.0"
    assert len(package.chapters) == 6
    assert automatic_course_generation_service.count_visual_specs(package) == 13
    assert automatic_course_generation_service.count_regional_exam_items(package) == 0


def test_phase10_v2_json_and_latex_references_keep_six_final_chapters():
    package = automatic_course_generation_service.parse_package(phase10_v2_package())
    latex_structure = automatic_course_generation_service.parse_latex(
        "\n".join(
            f"\\section{{Chapitre {index}}}\n\\label{{chapter_{index}}}\nTexte LaTeX du chapitre {index}."
            for index in range(1, 7)
        )
    )

    automatic_course_generation_service.validate_latex_references(package, latex_structure)
    final_chapter_refs = {
        chapter.id
        for chapter in package.chapters
        if automatic_course_generation_service.normalize_ref(chapter.latex_reference or chapter.id) in latex_structure["sections"]
    }

    assert len(package.chapters) == 6
    assert len(latex_structure["sections"]) == 6
    assert len(final_chapter_refs) == 6


def test_phase10_v2_visual_specs_are_merged_into_matching_chapter_blocks():
    package = automatic_course_generation_service.parse_package(phase10_v2_package())
    chapter = package.chapters[0]
    visuals = automatic_course_generation_service.visual_specs_for_chapter(package, chapter.id, chapter.latex_reference)
    blocks = automatic_course_generation_service.build_structured_blocks(
        chapter.id,
        [block.model_dump() for block in chapter.content_blocks],
        [{"type": "paragraph", "content": "Texte LaTeX enrichi."}],
        visuals,
    )

    visual_blocks = [block for block in blocks if block["type"] == "visual"]
    assert visual_blocks
    assert all(block["source_chapter_id"] == "chapter_1" for block in visual_blocks)
    assert {block["spec"]["status"] for block in visual_blocks} == {"to_provide_or_generate"}


def test_phase10_v2_import_accepts_regional_exam_statuses():
    items = [
        {"id": status, "status": status, "question": f"Question {status}"}
        for status in ("official", "indicative", "teacher_proposal", "to_verify")
    ]
    package = automatic_course_generation_service.parse_package(phase10_v2_package(regional_items=items))

    assert automatic_course_generation_service.count_regional_exam_items(package) == 4


def test_phase10_missing_latex_reference_is_reported_readably():
    package = automatic_course_generation_service.parse_package(phase10_v2_package())
    latex_structure = automatic_course_generation_service.parse_latex(phase10_latex(chapters_count=5))

    try:
        automatic_course_generation_service.validate_latex_references(package, latex_structure)
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "Reference LaTeX absente: chapter_6" in str(exc.detail)
    else:
        raise AssertionError("La reference LaTeX manquante aurait du etre signalee")
