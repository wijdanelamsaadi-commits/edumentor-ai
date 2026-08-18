import { useEffect, useMemo, useState } from 'react'
import {
  adaptProfessorCourseImport,
  analyzeProfessorCourseImport,
  fetchEducationLevels,
  fetchSubjects,
  getProfessorClassrooms,
  publishProfessorCourseImport,
  updateProfessorCourseImportSection,
  validateProfessorCourseImport,
} from '../services/api.js'

const STEPS = ['Importer', 'Analyser', 'Previsualiser', 'Publier et assigner']
const LEVELS = [
  { key: 'debutant', label: 'Debutant' },
  { key: 'intermediaire', label: 'Intermediaire' },
  { key: 'avance', label: 'Avance' },
]
const MODES = [
  { value: 'automatic_class', label: 'Automatique selon la classe' },
  { value: 'debutant', label: 'Debutant' },
  { value: 'intermediaire', label: 'Intermediaire' },
  { value: 'avance', label: 'Avance' },
  { value: 'create_three_versions', label: 'Creer les trois versions' },
]

function ProfessorAutomaticCourseImportPage() {
  const [classrooms, setClassrooms] = useState([])
  const [subjects, setSubjects] = useState([])
  const [educationLevels, setEducationLevels] = useState([])
  const [classroomId, setClassroomId] = useState('')
  const [subjectId, setSubjectId] = useState('')
  const [educationLevelId, setEducationLevelId] = useState('')
  const [adaptationMode, setAdaptationMode] = useState('automatic_class')
  const [jsonFile, setJsonFile] = useState(null)
  const [latexFile, setLatexFile] = useState(null)
  const [autoAssign, setAutoAssign] = useState(true)
  const [loading, setLoading] = useState(false)
  const [step, setStep] = useState(0)
  const [workflow, setWorkflow] = useState(null)
  const [message, setMessage] = useState(null)
  const [activeTab, setActiveTab] = useState('original')
  const [editingSection, setEditingSection] = useState(null)
  const [editValue, setEditValue] = useState('')

  useEffect(() => {
    Promise.allSettled([getProfessorClassrooms(), fetchSubjects(), fetchEducationLevels()])
      .then(([classroomResult, subjectResult, educationResult]) => {
        if (classroomResult.status === 'fulfilled') setClassrooms(Array.isArray(classroomResult.value) ? classroomResult.value : [])
        if (subjectResult.status === 'fulfilled') setSubjects(Array.isArray(subjectResult.value) ? subjectResult.value : [])
        if (educationResult.status === 'fulfilled') setEducationLevels(Array.isArray(educationResult.value) ? educationResult.value : [])
      })
      .catch((err) => setMessage(formatApiMessage(err.detail ?? err.message ?? 'Chargement impossible.')))
  }, [])

  const selectedClassroom = useMemo(
    () => classrooms.find((classroom) => String(classroom.id) === String(classroomId)),
    [classrooms, classroomId],
  )
  const adaptations = workflow?.adaptations || []
  const activeAdaptation = adaptations.find((item) => item.target_level === activeTab) || adaptations[0]
  const classLevelSummary = workflow?.result_summary?.class_level_summary || workflow?.source_summary?.class_level_summary
  const canPublish = workflow?.status === 'validated' || adaptations.some((item) => item.status === 'validated')

  function resetFeedback() {
    setMessage(null)
  }

  function resetAll() {
    setWorkflow(null)
    setStep(0)
    setActiveTab('original')
    setEditingSection(null)
    setEditValue('')
    resetFeedback()
  }

  async function analyze(event) {
    event.preventDefault()
    if (!jsonFile || !classroomId) {
      setMessage(formatApiMessage('Classe et fichier JSON obligatoires.'))
      return
    }
    setLoading(true)
    setMessage(formatApiMessage('Analyse NLP du contenu en cours...'))
    try {
      const response = await analyzeProfessorCourseImport({
        jsonFile,
        latexFile,
        classroomId,
        subjectId,
        educationLevelId,
        adaptationMode,
      })
      setWorkflow(response)
      setStep(1)
      setMessage(formatApiMessage('Analyse terminee. Vous pouvez maintenant generer les versions adaptees.'))
    } catch (err) {
      setMessage(formatApiMessage(err.detail ?? err.message ?? 'Analyse impossible.'))
    } finally {
      setLoading(false)
    }
  }

  async function adapt() {
    if (!workflow?.id) return
    setLoading(true)
    setMessage(formatApiMessage('Generation des brouillons adaptes en cours...'))
    try {
      const response = await adaptProfessorCourseImport(workflow.id, {
        mode: adaptationMode,
        target_levels: adaptationMode === 'create_three_versions' ? LEVELS.map((item) => item.key) : [],
      })
      setWorkflow(response)
      setActiveTab(response.adaptations?.[0]?.target_level || 'original')
      setStep(2)
      setMessage(formatApiMessage('Brouillons adaptes crees. Relisez et modifiez avant validation.'))
    } catch (err) {
      setMessage(formatApiMessage(err.detail ?? err.message ?? 'Adaptation impossible.'))
    } finally {
      setLoading(false)
    }
  }

  async function saveSection(section) {
    if (!workflow?.id || !section?.id) return
    setLoading(true)
    try {
      const response = await updateProfessorCourseImportSection(workflow.id, section.id, { adapted_content: editValue })
      setWorkflow(response)
      setEditingSection(null)
      setEditValue('')
      setMessage(formatApiMessage('Section modifiee. Validation professeur toujours requise.'))
    } catch (err) {
      setMessage(formatApiMessage(err.detail ?? err.message ?? 'Modification impossible.'))
    } finally {
      setLoading(false)
    }
  }

  async function validate() {
    if (!workflow?.id) return
    setLoading(true)
    try {
      const response = await validateProfessorCourseImport(workflow.id)
      setWorkflow(response)
      setStep(3)
      setMessage(formatApiMessage('Versions validees. Publication possible.'))
    } catch (err) {
      setMessage(formatApiMessage(err.detail ?? err.message ?? 'Validation impossible.'))
    } finally {
      setLoading(false)
    }
  }

  async function publish() {
    if (!workflow?.id) return
    setLoading(true)
    try {
      const response = await publishProfessorCourseImport(workflow.id, {
        auto_assign: autoAssign,
        adaptation_ids: adaptations.filter((item) => item.status === 'validated').map((item) => item.id),
      })
      setWorkflow(response)
      setMessage(formatApiMessage(buildPublishMessage(response)))
    } catch (err) {
      setMessage(formatApiMessage(err.detail ?? err.message ?? 'Publication impossible.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Creer automatiquement un cours</h1>
        <p>Importez, analysez et validez les versions adaptees avant publication.</p>
      </div>

      <StepBar step={step} />
      {message && <article className="panel-card"><FormattedApiMessage message={message} /></article>}

      <form className="panel-card admin-course-form" onSubmit={analyze}>
        <div className="panel-title">
          <h2>Etape 1 - Importer</h2>
          <p>Le cours ne sera pas publie automatiquement.</p>
        </div>

        <div className="admin-form-row">
          <label>Classe
            <select value={classroomId} onChange={(event) => {
              setClassroomId(event.target.value)
              resetAll()
            }}>
              <option value="">Selectionner une classe</option>
              {classrooms.map((classroom) => <option key={classroom.id} value={classroom.id}>{classroom.name}</option>)}
            </select>
          </label>
          <label>Matiere
            <select value={subjectId} onChange={(event) => {
              setSubjectId(event.target.value)
              resetFeedback()
            }}>
              <option value="">Detectee depuis le JSON</option>
              {subjects.map((subject) => <option key={subject.id} value={subject.id}>{subject.name}</option>)}
            </select>
          </label>
          <label>Niveau scolaire
            <select value={educationLevelId} onChange={(event) => {
              setEducationLevelId(event.target.value)
              resetFeedback()
            }}>
              <option value="">Detecte depuis le JSON</option>
              {educationLevels.map((level) => <option key={level.id} value={level.id}>{level.name}</option>)}
            </select>
          </label>
        </div>

        <div className="admin-form-row">
          <label>Mode d'adaptation
            <select value={adaptationMode} onChange={(event) => {
              setAdaptationMode(event.target.value)
              resetFeedback()
            }}>
              {MODES.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
            </select>
          </label>
          <label>Assignation apres publication
            <select value={String(autoAssign)} onChange={(event) => setAutoAssign(event.target.value === 'true')}>
              <option value="true">Assigner automatiquement</option>
              <option value="false">Ne pas assigner</option>
            </select>
          </label>
        </div>

        <div className="admin-form-row">
          <label>Package JSON obligatoire
            <input accept=".json,application/json" type="file" onChange={(event) => {
              setJsonFile(event.target.files?.[0] || null)
              resetAll()
            }} />
          </label>
          <label>Fichier LaTeX facultatif
            <input accept=".tex,.latex,text/plain" type="file" onChange={(event) => {
              setLatexFile(event.target.files?.[0] || null)
              resetAll()
            }} />
          </label>
        </div>

        <button className="primary-button" disabled={loading} type="submit">
          {loading && step === 0 ? 'Analyse en cours...' : 'Analyser le contenu'}
        </button>
      </form>

      {workflow && (
        <article className="panel-card">
          <div className="panel-title">
            <h2>Etape 2 - Analyser</h2>
            <p>{workflow.status}</p>
          </div>
          <div className="dashboard-stats">
            <Metric title="Sections detectees" value={workflow.result_summary?.sections_count ?? workflow.source_summary?.analysis?.sections_count ?? '--'} />
            <Metric title="Niveau estime" value={workflow.result_summary?.estimated_level ?? workflow.source_summary?.analysis?.estimated_level ?? '--'} />
            <Metric title="Niveau dominant classe" value={classLevelSummary?.dominant_level || '--'} />
            <Metric title="Etudiants" value={classLevelSummary?.total_students ?? selectedClassroom?.students_count ?? '--'} />
          </div>
          <SectionCounts counts={workflow.source_summary?.analysis?.section_counts || workflow.result_summary?.section_counts || {}} />
          <Warnings items={workflow.source_summary?.analysis?.warnings || workflow.result_summary?.warnings || []} />
          <button className="primary-button" disabled={loading} type="button" onClick={adapt}>
            {loading && step === 1 ? 'Adaptation en cours...' : 'Generer les versions adaptees'}
          </button>
        </article>
      )}

      {workflow?.original && (
        <article className="panel-card">
          <div className="panel-title">
            <h2>Etape 3 - Previsualiser</h2>
            <p>Relisez le contenu original et les brouillons adaptes.</p>
          </div>
          <div className="tab-row">
            <button className={activeTab === 'original' ? 'active' : ''} type="button" onClick={() => setActiveTab('original')}>Original</button>
            {LEVELS.map((level) => (
              <button
                className={activeTab === level.key ? 'active' : ''}
                disabled={!adaptations.some((item) => item.target_level === level.key)}
                key={level.key}
                type="button"
                onClick={() => setActiveTab(level.key)}
              >
                {level.label}
              </button>
            ))}
          </div>

          {activeTab === 'original'
            ? <OriginalPreview original={workflow.original} />
            : (
              <AdaptationPreview
                adaptation={activeAdaptation}
                editValue={editValue}
                editingSection={editingSection}
                loading={loading}
                onCancel={() => {
                  setEditingSection(null)
                  setEditValue('')
                }}
                onEdit={(section) => {
                  setEditingSection(section.id)
                  setEditValue(section.adapted_content || '')
                }}
                onSave={saveSection}
                onSetEditValue={setEditValue}
              />
            )}
          {adaptations.length > 0 && (
            <button className="secondary-button" disabled={loading} type="button" onClick={validate}>Valider les versions</button>
          )}
        </article>
      )}

      {workflow && (
        <article className="panel-card">
          <div className="panel-title">
            <h2>Etape 4 - Publier et assigner</h2>
            <p>La publication cree le cours seulement apres validation.</p>
          </div>
          <div className="dashboard-stats">
            <Metric title="Cours" value={workflow.course_id || 'Non publie'} />
            <Metric title="Versions" value={adaptations.length || workflow.variants_count || 0} />
            <Metric title="Classe cible" value={selectedClassroom?.name || workflow.classroom_id || '--'} />
          </div>
          <button className="primary-button" disabled={loading || !canPublish || Boolean(workflow.course_id)} type="button" onClick={publish}>
            {loading && step === 3 ? 'Publication en cours...' : 'Publier et assigner'}
          </button>
          {!canPublish && <p className="muted-text">Validez les brouillons avant de publier.</p>}
        </article>
      )}
    </section>
  )
}

function StepBar({ step }) {
  return (
    <div className="panel-card">
      <div className="dashboard-stats">
        {STEPS.map((label, index) => (
          <article className="metric-card" key={label}>
            <p>Etape {index + 1}</p>
            <h2>{label}</h2>
            <strong>{index <= step ? 'En cours' : 'A venir'}</strong>
          </article>
        ))}
      </div>
    </div>
  )
}

function Metric({ title, value }) {
  return <article className="metric-card"><p>{title}</p><h2>{formatDisplayValue(value)}</h2></article>
}

function SectionCounts({ counts }) {
  const entries = Object.entries(counts || {})
  if (!entries.length) return null
  return (
    <div className="resource-tags">
      {entries.map(([key, value]) => <span key={key}>{key}: {value}</span>)}
    </div>
  )
}

function Warnings({ items }) {
  if (!items?.length) return null
  return (
    <div className="empty-state">
      {items.map((item) => <p key={item}>{item}</p>)}
    </div>
  )
}

function OriginalPreview({ original }) {
  return (
    <div className="course-list">
      {(original?.chapters || []).map((chapter) => (
        <article className="course-card" key={chapter.source_chapter_id}>
          <h3>{chapter.title}</h3>
          {(chapter.blocks || []).slice(0, 8).map((block, index) => (
            <div className="chapter-content-block" key={`${chapter.source_chapter_id}-${block.source_block_id || index}`}>
              <strong>{block.type}</strong>
              <p>{block.content}</p>
            </div>
          ))}
        </article>
      ))}
    </div>
  )
}

function AdaptationPreview({ adaptation, editingSection, editValue, loading, onEdit, onCancel, onSave, onSetEditValue }) {
  if (!adaptation) return <p className="muted-text">Aucune version generee pour ce niveau.</p>
  return (
    <div className="course-list">
      <div className="resource-tags">
        <span>{adaptation.target_level}</span>
        <span>{adaptation.status}</span>
        <span>{adaptation.sections_count} sections</span>
      </div>
      {(adaptation.sections || []).map((section) => (
        <article className="course-card" key={section.id}>
          <div className="panel-title">
            <h3>{section.metadata?.title || section.section_type}</h3>
            <p>{section.section_type} - {section.source_level} vers {section.target_level}</p>
          </div>
          <StructuredSectionPreview section={section} />
          {editingSection === section.id ? (
            <>
              <textarea value={editValue} onChange={(event) => onSetEditValue(event.target.value)} rows={5} />
              <div className="admin-actions">
                <button className="primary-button" disabled={loading} type="button" onClick={() => onSave(section)}>Enregistrer</button>
                <button className="secondary-button" disabled={loading} type="button" onClick={onCancel}>Annuler</button>
              </div>
            </>
          ) : (
            <>
              <p>{section.adapted_content}</p>
              <button className="secondary-button" type="button" onClick={() => onEdit(section)}>Modifier</button>
            </>
          )}
        </article>
      ))}
    </div>
  )
}

function StructuredSectionPreview({ section }) {
  const payload = section.metadata?.adapted_payload || {}
  return (
    <div className="import-section-preview">
      <PreviewRow label="Titre" value={section.metadata?.title || payload.title || section.section_type} />
      <PreviewRow label="Type" value={section.section_type} />
      <PreviewRow label="Niveau" value={`${section.source_level} -> ${section.target_level}`} />
      <PreviewRow label="Contenu original" value={section.original_content} muted />
      <PreviewRow label="Contenu adapte" value={payload.content || section.adapted_content} />
      <PreviewRow label="Exemple" value={payload.example} />
      <PreviewRow label="Question" value={payload.question} />
      <PreviewList label="Choix" items={payload.choices} />
      <PreviewRow label="Reponse" value={payload.answer} />
      <PreviewRow label="Explication" value={payload.explanation} />
      <PreviewRow label="Solution" value={payload.solution} />
      <PreviewList label="Liste" items={payload.items} />
    </div>
  )
}

function PreviewRow({ label, value, muted = false }) {
  if (value === undefined || value === null || value === '') return null
  return (
    <div className="import-preview-row">
      <strong>{label}</strong>
      <p className={muted ? 'muted-text' : ''}>{String(value)}</p>
    </div>
  )
}

function PreviewList({ label, items }) {
  if (!Array.isArray(items) || items.length === 0) return null
  return (
    <div className="import-preview-row">
      <strong>{label}</strong>
      <ul>
        {items.map((item, index) => (
          <li key={`${label}-${index}-${String(item)}`}>{String(item)}</li>
        ))}
      </ul>
    </div>
  )
}

function buildPublishMessage(result) {
  return {
    title: result?.result_summary?.course_title || 'Cours publie',
    courseId: result?.course_id,
    status: result?.status,
    chaptersCount: result?.chapters_count ?? result?.result_summary?.chapters_count,
    assignedStudents: result?.assigned_students_count ?? result?.result_summary?.assigned_students,
  }
}

function formatApiMessage(value) {
  if (value === null || value === undefined || value === '') return { type: 'text', text: '' }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return { type: 'text', text: String(value) }
  if (Array.isArray(value)) {
    if (value.every(isFastApiValidationError)) {
      return { type: 'list', items: value.map((item) => `${formatLocation(item.loc)} : ${item.msg || 'champ invalide'}`) }
    }
    return { type: 'list', items: value.map((item) => formatDisplayValue(item)) }
  }
  if (typeof value === 'object') {
    if (value.title || value.courseId || value.status) {
      return {
        type: 'summary',
        rows: [
          ['Titre du cours', value.title || 'Cours'],
          ['Course ID', value.courseId || '--'],
          ['Statut', value.status || '--'],
          ['Nombre de chapitres', value.chaptersCount ?? '--'],
          ['Etudiants assignes', value.assignedStudents ?? '--'],
        ],
      }
    }
    return { type: 'pre', text: JSON.stringify(value, null, 2) }
  }
  return { type: 'text', text: String(value) }
}

function FormattedApiMessage({ message }) {
  if (!message?.text && !message?.items?.length && !message?.rows?.length) return null
  if (message.type === 'list') return <ul>{message.items.map((item) => <li key={item}>{item}</li>)}</ul>
  if (message.type === 'summary') {
    return <ul>{message.rows.map(([label, value]) => <li key={label}><strong>{label}</strong> : {formatDisplayValue(value)}</li>)}</ul>
  }
  if (message.type === 'pre') return <pre>{message.text}</pre>
  return <p>{message.text}</p>
}

function isFastApiValidationError(item) {
  return item && typeof item === 'object' && Array.isArray(item.loc) && 'msg' in item
}

function formatLocation(loc) {
  return Array.isArray(loc) ? loc.filter((item) => item !== 'body').join('.') : 'champ'
}

function formatDisplayValue(value) {
  if (value === null || value === undefined || value === '') return '--'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value, null, 2)
}

export default ProfessorAutomaticCourseImportPage
