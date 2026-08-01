from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PackageCourse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3)
    summary: str = Field(min_length=3)
    description: str = Field(min_length=3)
    subject: str = Field(min_length=2)
    education_level: str = Field(min_length=2)
    difficulty: str = Field(min_length=2)
    estimated_duration_hours: int | float = Field(gt=0)
    prerequisites: list[str] = Field(default_factory=list)


class PackageTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str = "Maroc"
    cycle: str = "1ere_bac"
    academic_year: str = Field(min_length=4)
    region: str = Field(min_length=2)
    stream: str = ""
    exam_type: str = "regional"


class PackageVocabulary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str = Field(min_length=1)
    definition: str = Field(min_length=1)


class PackageWorkChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = ""
    characters: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    vocabulary: list[PackageVocabulary] = Field(default_factory=list)


class PackageWork(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    author: str = ""
    genre: str = ""
    context: str = ""
    chapters: list[PackageWorkChapter] = Field(default_factory=list)


class PackageContentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    title: str | None = None
    content: str | None = None
    question: str | None = None
    solution: str | None = None
    answer: str | None = None
    explanation: str | None = None
    items: list[str] | None = None
    choices: list[str] | None = None
    metadata: dict[str, Any] | None = None
    id: str | None = None

    @model_validator(mode="after")
    def require_text_content(self):
        if not (self.content or self.question or self.items):
            raise ValueError("Chaque bloc doit contenir content, question ou items")
        return self



class VisualSpec(BaseModel):
    """Specification d'un visuel pedagogique V2.

    Les champs historiques restent acceptes pour preserver la compatibilite
    avec les payloads V1/tests existants, tandis que les champs du JSON V2
    complet sont explicitement types.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    type: Literal[
        "mermaid",
        "svg",
        "image",
        "table",
        "timeline",
        "character_map",
        "comparison_chart",
    ]
    title: str | None = None

    # Champs V2 utilises par le package regional.
    placement: str | None = None
    alt_text: str | None = None
    mermaid_code: str | None = None
    file_path: str | None = None
    license_status: str | None = None
    data_source: str | None = None
    rendering: str | None = None
    columns: list[str] | None = None

    # Champs historiques / generiques deja acceptes par le projet.
    description: str | None = None
    content: str | None = None
    data: dict[str, Any] | list[Any] | str | None = None
    source: str | None = None
    source_ref: str | None = None
    chapter_id: str | None = None
    chapter_ref: str | None = None
    status: str | None = None
    path: str | None = None
    image_path: str | None = None
    alt: str | None = None
    caption: str | None = None
    rows: list[Any] | None = None
    items: list[Any] | None = None
    metadata: dict[str, Any] | None = None


class ExamTraining(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Champs V2 du package.
    linked_exam_ids: list[str] = Field(default_factory=list)
    question_types: list[str] = Field(default_factory=list)
    grading_focus: list[str] = Field(default_factory=list)
    status: str | None = None

    # Champs historiques / generiques.
    objectives: list[str] = Field(default_factory=list)
    instructions: str | None = None
    methods: list[str] = Field(default_factory=list)
    activities: list[Any] = Field(default_factory=list)
    exercises: list[Any] = Field(default_factory=list)
    questions: list[Any] = Field(default_factory=list)
    correction: str | None = None
    criteria: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class PackageChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    order: int = Field(gt=0)
    objectives: list[str] = Field(min_length=1)
    skills: list[str] = Field(min_length=1)
    content_blocks: list[PackageContentBlock] = Field(min_length=1)
    latex_reference: str | None = None
    latex_ref: str | None = None
    source_ref: str | None = None
    visuals: list[VisualSpec] = Field(default_factory=list)
    exam_training: ExamTraining | None = None
    content_quality_requirements: "ContentQualityRequirements | None" = None

    @model_validator(mode="after")
    def normalize_references(self):
        if not self.latex_reference:
            self.latex_reference = self.latex_ref or self.source_ref
        return self


class ContentQualityRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Contrat V2 par chapitre.
    minimum_exercises: int | None = Field(default=None, ge=0)
    minimum_corrections: int | None = Field(default=None, ge=0)
    exactly_one_mini_assessment: bool | None = None
    no_empty_corrections: bool | None = None
    no_truncated_sentences: bool | None = None
    chapter_specific_content: bool | None = None

    # Champs historiques / generiques.
    min_words_per_chapter: int | None = Field(default=None, ge=0)
    max_words_per_chapter: int | None = Field(default=None, ge=0)
    required_sections: list[str] = Field(default_factory=list)
    exercises_per_chapter: int | None = Field(default=None, ge=0)
    corrections_required: bool | None = None
    citation_policy: str | None = None
    language: str | None = None
    tone: str | None = None
    levels: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class CitationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exact_quotes: str
    page_numbers: str
    invented_details: bool


class SourcePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Champs V2 du package.
    json_role: str | None = None
    latex_role: str | None = None
    images_storage: str | None = None
    images_base64_allowed: bool | None = None
    citation_policy: CitationPolicy | str | None = None
    correction_labels: list[
        Literal["official", "indicative", "teacher_proposal", "to_verify"]
    ] = Field(default_factory=list)

    # Champs historiques / generiques.
    allowed_sources: list[str] = Field(default_factory=list)
    forbidden_sources: list[str] = Field(default_factory=list)
    allow_external_knowledge: bool | None = None
    citation_required: bool | None = None
    no_exact_quotes: bool | None = None
    no_page_numbers_without_source: bool | None = None
    policy: str | None = None
    constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class AssetConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Champs V2 du package.
    images_root: str | None = None
    exam_subjects_root: str | None = None
    exam_corrections_root: str | None = None
    generated_diagrams_root: str | None = None
    supported_visual_types: list[str] = Field(default_factory=list)

    # Champs historiques / generiques.
    images: list[Any] = Field(default_factory=list)
    diagrams: list[Any] = Field(default_factory=list)
    output_dir: str | None = None
    naming: str | dict[str, Any] | None = None
    formats: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    generate_missing: bool | None = None
    assets: list[Any] | dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class RequiredOutputsPerChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercises: int = Field(ge=0)
    corrections: int = Field(ge=0)
    mini_assessments: int = Field(ge=0)


class AIGenerationRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Champs V2 du package.
    grounding: str | None = None
    adaptation_levels: list[str] = Field(default_factory=list)
    required_outputs_per_chapter: RequiredOutputsPerChapter | None = None
    forbidden_behaviors: list[str] = Field(default_factory=list)

    # Champs historiques / generiques.
    enabled: bool | None = None
    provider: str | None = None
    model: str | None = None
    levels: list[str] = Field(default_factory=list)
    prompt_style: str | None = None
    retries: int | None = None
    timeout_seconds: int | None = None
    fallback_policy: str | None = None
    rules: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class RegionalExamItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    title: str | None = None
    year: int | None = None
    region: str | None = None
    academic_year: str | None = None
    session: str | None = None
    stream: str | None = None
    subject: str | None = None
    work: str | None = None
    subject_source: str | None = None
    correction_source: str | None = None
    correction_status: Literal[
        "official", "indicative", "teacher_proposal", "to_verify"
    ] | None = None

    # Alias historique conserve pour les anciens payloads.
    status: Literal[
        "official", "indicative", "teacher_proposal", "to_verify"
    ] | None = None

    question: str | None = None
    answer: str | None = None
    correction: str | None = None
    source: str | None = None
    points: int | float | None = None
    duration_minutes: int | None = None
    skills: list[str] = Field(default_factory=list)
    chapters: list[str] = Field(default_factory=list)
    questions: list[Any] = Field(default_factory=list)
    answers: list[Any] = Field(default_factory=list)
    grading_scale: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def normalize_correction_status(self):
        if self.correction_status is None and self.status is not None:
            self.correction_status = self.status
        elif self.status is None and self.correction_status is not None:
            self.status = self.correction_status
        return self


class RegionalExamScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    years: list[int] = Field(default_factory=list)
    works: list[str] = Field(default_factory=list)
    target_count: int = Field(default=0, ge=0)


class RegionalExamVerificationRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    official_source_preferred: bool = True
    unofficial_corrections_must_be_labeled: bool = True
    required_fields: list[str] = Field(default_factory=list)


class RegionalExamBank(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    scope: RegionalExamScope | None = None
    verification_rules: RegionalExamVerificationRules | None = None
    items: list[RegionalExamItem] = Field(default_factory=list)

    # Champs historiques / generiques.
    title: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class LatexExportConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None

    # Champs V2 du package.
    source: str | None = None
    outputs: list[str] = Field(default_factory=list)
    diagram_support: list[str] = Field(default_factory=list)

    # Champs historiques / generiques.
    template: str | None = None
    include_visuals: bool | None = None
    output_filename: str | None = None
    compiler: str | None = None
    packages: list[str] = Field(default_factory=list)
    options: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

class AssessmentLevelRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direct_questions_ratio: float = Field(ge=0, le=1)
    analysis_questions_ratio: float = Field(ge=0, le=1)
    production_questions_ratio: float = Field(ge=0, le=1)


class AssessmentBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions_per_assessment: int = Field(default=10, ge=2, le=60)
    duration_minutes: int = Field(default=30, ge=1, le=240)
    passing_score: int = Field(default=70, ge=1, le=100)
    max_attempts: int = Field(default=2, ge=1, le=10)
    skills: list[str] = Field(min_length=1)
    levels: dict[Literal["debutant", "intermediaire", "avance"], AssessmentLevelRules]


class DiagnosticBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions_bank_size: int = Field(default=30, ge=20, le=120)
    questions_per_test: int = Field(default=20, ge=5, le=30)
    levels: dict[Literal["debutant", "intermediaire", "avance"], int] = Field(
        default_factory=lambda: {"debutant": 10, "intermediaire": 10, "avance": 10}
    )
    themes: list[str] = Field(default_factory=list)


class PedagogicalPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "2.0"]
    course: PackageCourse
    target: PackageTarget
    works: list[PackageWork] = Field(default_factory=list)
    chapters: list[PackageChapter] = Field(min_length=1)
    assessment_blueprint: AssessmentBlueprint
    diagnostic_blueprint: DiagnosticBlueprint | None = None
    visuals: list[VisualSpec] = Field(default_factory=list)
    exam_training: ExamTraining | None = None
    content_quality_requirements: ContentQualityRequirements | None = None
    source_policy: SourcePolicy | None = None
    assets: AssetConfiguration | None = None
    ai_generation_rules: AIGenerationRules | None = None
    regional_exam_bank: RegionalExamBank | None = None
    latex_export: LatexExportConfiguration | None = None

    @field_validator("chapters")
    @classmethod
    def unique_chapter_ids(cls, chapters: list[PackageChapter]) -> list[PackageChapter]:
        ids = [chapter.id for chapter in chapters]
        if len(ids) != len(set(ids)):
            raise ValueError("Les identifiants de chapitres doivent etre uniques")
        return chapters

    @field_validator("works")
    @classmethod
    def unique_work_ids(cls, works: list[PackageWork]) -> list[PackageWork]:
        ids = [work.id for work in works]
        if len(ids) != len(set(ids)):
            raise ValueError("Les identifiants d'oeuvres doivent etre uniques")
        return works


# Resolution explicite des references differees Pydantic.
PackageChapter.model_rebuild()
PedagogicalPackage.model_rebuild()