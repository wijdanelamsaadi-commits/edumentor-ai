from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceBoundText(BaseModel):
    title: str = ""
    content: str
    source_ids: list[str] = Field(default_factory=list)


class KeyConcept(BaseModel):
    term: str
    definition: str
    example: str = ""
    source_ids: list[str] = Field(default_factory=list)


class ExerciseItem(BaseModel):
    prompt: str
    expected_answer: str = ""
    hint: str = ""
    source_ids: list[str] = Field(default_factory=list)


class Flashcard(BaseModel):
    front: str
    back: str
    source_ids: list[str] = Field(default_factory=list)


class KnowledgeCheckItem(BaseModel):
    question: str
    options: list[str]
    answer: str
    explanation: str
    source_ids: list[str] = Field(default_factory=list)

    @field_validator("options")
    @classmethod
    def require_options(cls, value: list[str]) -> list[str]:
        if len([item for item in value if str(item).strip()]) < 2:
            raise ValueError("at least two options are required")
        return value[:4]


class GeneratedChapterContent(BaseModel):
    chapter_title: str
    level: str
    learning_objectives: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    introduction: str
    detailed_explanations: list[SourceBoundText] = Field(default_factory=list)
    key_concepts: list[KeyConcept] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    literary_devices: list[str] = Field(default_factory=list)
    worked_examples: list[SourceBoundText] = Field(default_factory=list)
    guided_exercises: list[ExerciseItem] = Field(default_factory=list)
    independent_exercises: list[ExerciseItem] = Field(default_factory=list)
    solutions: list[str] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    revision_summary: str
    flashcards: list[Flashcard] = Field(default_factory=list)
    knowledge_check: list[KnowledgeCheckItem] = Field(default_factory=list)
    validation_status: str = "needs_review"


class VocabularyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str
    definition: str


class AdaptiveKeyPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    content: str


class GuidedExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    instruction: str = ""
    content: str
    steps: list[str] = Field(default_factory=list)
    answer: str = ""


class AdaptiveLearningSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str
    steps: list[str] = Field(default_factory=list)
    pitfalls: list[str] = Field(default_factory=list)
    memory_tip: str = ""

    def as_text_items(self) -> list[str]:
        items = [self.method, *self.steps, *self.pitfalls, self.memory_tip]
        return [str(item).strip() for item in items if str(item).strip()]


class PracticeQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    instruction: str = ""
    difficulty: str = ""
    expected_elements: list[str] = Field(default_factory=list)
    expected_answer: str = ""
    explanation: str

    @model_validator(mode="after")
    def fill_expected_answer_from_elements(self):
        if not self.expected_answer and self.expected_elements:
            self.expected_answer = " ".join(self.expected_elements)
        return self


class AdaptiveGeneratedBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    type: Literal["heading", "paragraph", "definition", "example", "methodology", "warning", "key_points", "exercise", "correction", "summary", "mini_assessment", "visual"]
    title: str = ""
    content: str | list[str] | dict = ""
    section: str = "resume"
    original_block_type: str | None = None


class AdaptiveChapterVariantContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    explanation: str
    key_points: list[AdaptiveKeyPoint] = Field(default_factory=list)
    vocabulary: list[VocabularyItem] = Field(default_factory=list)
    guided_example: GuidedExample
    learning_support: AdaptiveLearningSupport
    practice_question: PracticeQuestion
    blocks: list[AdaptiveGeneratedBlock] = Field(default_factory=list)


class AdaptiveLessonBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    type: str
    title: str = ""
    content: str | list[str] | dict = ""
    section: str = "resume"
    source_block_id: str | None = None
    source_chapter_id: str | None = None
    source_hash: str | None = None
    original_block_type: str | None = None
    level: Literal["debutant", "intermediaire", "avance"]
    generation_method: Literal["ai_generated", "deterministic_fallback", "official_source"] = "ai_generated"


class AdaptiveChapterVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["debutant", "intermediaire", "avance"]
    chapter_source_id: str
    title: str
    summary: str
    explanation: str
    key_points: list[str] = Field(default_factory=list)
    vocabulary: list[VocabularyItem] = Field(default_factory=list)
    guided_example: GuidedExample
    learning_support: list[str] = Field(default_factory=list)
    practice_question: PracticeQuestion
    blocks: list[AdaptiveLessonBlock] = Field(default_factory=list)
    source_block_ids: list[str] = Field(default_factory=list)
    generation_method: Literal["ai_generated", "deterministic_fallback"] = "ai_generated"
    model: str | None = None
    generated_at: str

    @field_validator("key_points", "learning_support", "source_block_ids")
    @classmethod
    def require_non_empty_items(cls, value: list[str]) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()]


class AdaptiveChapterVariantSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_source_id: str
    variants: dict[Literal["debutant", "intermediaire", "avance"], AdaptiveChapterVariant]

    @field_validator("variants")
    @classmethod
    def require_all_levels(cls, value: dict[str, AdaptiveChapterVariant]) -> dict[str, AdaptiveChapterVariant]:
        missing = {"debutant", "intermediaire", "avance"} - set(value)
        if missing:
            raise ValueError(f"missing variants: {', '.join(sorted(missing))}")
        return value


class GeneratedQuestion(BaseModel):
    question_text: str
    question_type: str = "multiple_choice"
    choices: list[str]
    correct_answer: str
    explanation: str
    points: float = 1
    difficulty: str
    target_level: str
    chapter_id: int | None = None
    skill: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    generation_method: str = "ai_generated"
    question_hash: str | None = None

    @field_validator("choices")
    @classmethod
    def require_four_choices(cls, value: list[str]) -> list[str]:
        clean = [str(item).strip() for item in value if str(item).strip()]
        if len(clean) < 2:
            raise ValueError("at least two choices are required")
        return clean[:4]


class RemediationGeneration(BaseModel):
    identified_misconception: str
    simple_explanation: str
    step_by_step_explanation: list[str] = Field(default_factory=list)
    new_example: str
    guided_exercise: ExerciseItem
    independent_exercise: ExerciseItem
    solutions: list[str] = Field(default_factory=list)
    micro_summary: str
    follow_up_questions: list[str] = Field(default_factory=list)


class StudyPathRecommendation(BaseModel):
    title: str
    reason: str
    ordered_steps: list[dict] = Field(default_factory=list)
    validation_status: str = "needs_backend_validation"


class PedagogicalAnalysis(BaseModel):
    measured_facts: list[str] = Field(default_factory=list)
    interpretation: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    priority_actions: list[str] = Field(default_factory=list)
