import { useEffect, useState } from 'react'
import { getProfessorClassrooms, getProfessorCoursePackageImportStatus, importProfessorCoursePackage } from '../services/api.js'

function ProfessorAutomaticCourseImportPage() {
  const [classrooms, setClassrooms] = useState([])
  const [classroomId, setClassroomId] = useState('')
  const [jsonFile, setJsonFile] = useState(null)
  const [latexFile, setLatexFile] = useState(null)
  const [autoAssign, setAutoAssign] = useState(true)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [message, setMessage] = useState(null)

  useEffect(() => {
    getProfessorClassrooms()
      .then(setClassrooms)
      .catch((err) => setMessage(formatApiMessage(err.detail ?? err.message ?? 'Impossible de charger les classes.')))
  }, [])

  function resetImportFeedback() {
    setMessage(null)
    setResult(null)
  }

  async function submit(event) {
    event.preventDefault()
    if (!jsonFile || !classroomId) {
      setMessage(formatApiMessage('Classe et fichier JSON obligatoires.'))
      return
    }
    setLoading(true)
    setMessage(formatApiMessage('Génération en cours...'))
    try {
      const response = await importProfessorCoursePackage({ jsonFile, latexFile, classroomId, autoAssign })
      const fresh = response.id ? await getProfessorCoursePackageImportStatus(response.id) : response
      setResult(fresh)
      setMessage(formatApiMessage(buildSuccessMessage(fresh)))
    } catch (err) {
      setMessage(formatApiMessage(err.detail ?? err.message ?? 'Génération impossible. Corrigez ou remplacez le fichier source.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Créer automatiquement un cours</h1>
        <p>Importez un package pédagogique JSON et, si nécessaire, un fichier LaTeX facultatif.</p>
      </div>

      {message && <article className="panel-card"><FormattedApiMessage message={message} /></article>}

      <form className="panel-card admin-course-form" onSubmit={submit}>
        <div className="admin-form-row">
          <label>Classe
            <select value={classroomId} onChange={(event) => {
              setClassroomId(event.target.value)
              resetImportFeedback()
            }}>
              <option value="">Sélectionner une classe</option>
              {classrooms.map((classroom) => <option key={classroom.id} value={classroom.id}>{classroom.name}</option>)}
            </select>
          </label>
          <label>Assignation
            <select value={String(autoAssign)} onChange={(event) => {
              setAutoAssign(event.target.value === 'true')
              resetImportFeedback()
            }}>
              <option value="true">Assigner automatiquement</option>
              <option value="false">Ne pas assigner</option>
            </select>
          </label>
        </div>

        <div className="admin-form-row">
          <label>Package JSON obligatoire
            <input accept=".json,application/json" type="file" onChange={(event) => {
              setJsonFile(event.target.files?.[0] || null)
              resetImportFeedback()
            }} />
          </label>
          <label>Fichier LaTeX facultatif
            <input accept=".tex,.latex,text/plain" type="file" onChange={(event) => {
              setLatexFile(event.target.files?.[0] || null)
              resetImportFeedback()
            }} />
          </label>
        </div>

        <button className="primary-button" disabled={loading} type="submit">
          {loading ? 'Génération en cours...' : 'Générer automatiquement'}
        </button>
      </form>

      {result && (
        <article className="panel-card">
          <div className="panel-title"><h2>Résultat de génération</h2><p>{formatDisplayValue(result.status)}</p></div>
          <div className="dashboard-stats">
            <article className="metric-card"><p>Cours</p><h2>{result.course_id || '--'}</h2><strong>{formatDisplayValue(getCourseTitle(result))}</strong></article>
            <article className="metric-card"><p>Chapitres</p><h2>{formatDisplayValue(result.chapters_count ?? result.result_summary?.chapters_count ?? '--')}</h2><strong>Visuels : {formatDisplayValue(getVisualsCount(result))}</strong></article>
            <article className="metric-card"><p>Questions</p><h2>{formatDisplayValue(result.questions_count ?? '--')}</h2><strong>{formatDisplayValue(result.assigned_students_count ?? result.assessment_assignments ?? 0)} assignations</strong></article>
          </div>
          {result.error_message && <FormattedApiMessage message={formatApiMessage(result.error_message)} />}
        </article>
      )}
    </section>
  )
}

function buildSuccessMessage(result) {
  if (!result || typeof result !== 'object') return result
  return {
    title: getCourseTitle(result),
    courseId: result.course_id,
    status: result.status,
    chaptersCount: result.chapters_count ?? result.result_summary?.chapters_count,
    visualsCount: getVisualsCount(result),
    examsCount: getRegionalExamsCount(result),
  }
}

function getCourseTitle(result) {
  return result?.result_summary?.course_title || result?.course_title || result?.title || 'Cours généré'
}

function getVisualsCount(result) {
  return result?.visuals_count ?? result?.result_summary?.visuals_count ?? result?.schemas_count ?? result?.diagrams_count ?? 0
}

function getRegionalExamsCount(result) {
  return result?.regional_exams_count ?? result?.result_summary?.regional_exams_count ?? result?.exam_count ?? 0
}

function formatApiMessage(value) {
  if (value === null || value === undefined || value === '') {
    return { type: 'text', text: '' }
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return { type: 'text', text: String(value) }
  }
  if (Array.isArray(value)) {
    if (value.every(isFastApiValidationError)) {
      return {
        type: 'list',
        items: value.map((item) => `${formatLocation(item.loc)} : ${item.msg || 'champ invalide'}`),
      }
    }
    return {
      type: 'list',
      items: value.map((item) => formatDisplayValue(item)),
    }
  }
  if (typeof value === 'object') {
    if (value.title || value.courseId || value.status) {
      return {
        type: 'summary',
        rows: [
          ['Titre du cours', value.title || 'Cours généré'],
          ['Course ID', value.courseId || '--'],
          ["Statut de l'import", value.status || '--'],
          ['Nombre de chapitres', value.chaptersCount ?? '--'],
          ['Nombre de schémas/visuels', value.visualsCount ?? 0],
          ["Nombre d'examens régionaux", value.examsCount ?? 0],
        ],
      }
    }
    return { type: 'pre', text: JSON.stringify(value, null, 2) }
  }
  return { type: 'text', text: String(value) }
}

function FormattedApiMessage({ message }) {
  if (!message?.text && !message?.items?.length && !message?.rows?.length) return null
  if (message.type === 'list') {
    return <ul>{message.items.map((item) => <li key={item}>{item}</li>)}</ul>
  }
  if (message.type === 'summary') {
    return (
      <div>
        <p>Cours généré automatiquement.</p>
        <ul>{message.rows.map(([label, value]) => <li key={label}><strong>{label}</strong> : {formatDisplayValue(value)}</li>)}</ul>
      </div>
    )
  }
  if (message.type === 'pre') {
    return <pre>{message.text}</pre>
  }
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
