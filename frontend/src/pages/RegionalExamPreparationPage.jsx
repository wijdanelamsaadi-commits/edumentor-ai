import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getRegionalExamPreparation } from '../services/api.js'
import {
  adaptPedagogicalText,
  analyzeFigure,
  classifyExamCompetence,
  formatNlpError,
  generateQuestionCorrection,
  getNlpUnits,
  predictLevel,
} from '../services/nlpApi.js'

const LEVELS = [
  { value: 'debutant', label: 'Débutant' },
  { value: 'intermediaire', label: 'Intermédiaire' },
  { value: 'avance', label: 'Avancé' },
]

const TASKS = [
  { value: 'comprehension', label: 'Compréhension' },
  { value: 'interpretation', label: 'Interprétation' },
  { value: 'langue', label: 'Langue' },
]

function RegionalExamPreparationPage() {
  const [data, setData] = useState(null)
  const [message, setMessage] = useState('')
  const [units, setUnits] = useState([])
  const [unitsMessage, setUnitsMessage] = useState('')

  useEffect(() => {
    let cancelled = false
    Promise.allSettled([
      getRegionalExamPreparation(),
      getNlpUnits(),
    ]).then(([regionalResponse, unitsResponse]) => {
      if (cancelled) return
      if (regionalResponse.status === 'fulfilled') {
        setData(regionalResponse.value)
      } else {
        setMessage(regionalResponse.reason?.message || 'Préparation régionale indisponible.')
      }
      if (unitsResponse.status === 'fulfilled') {
        setUnits(unitsResponse.value.data.units || [])
      } else {
        setUnitsMessage(formatNlpError(unitsResponse.reason, 'Unités NLP indisponibles.'))
      }
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (!data) {
    return <section className="page-section dashboard-page"><article className="panel-card"><p>{message || 'Chargement...'}</p></article></section>
  }

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Préparation au régional de français</h1>
        <p>1ère Bac Maroc - indicateur pédagogique basé sur vos données d'apprentissage.</p>
      </div>

      <div className="dashboard-stats">
        <article className="metric-card"><p>Jours restants</p><h2>{data.days_remaining ?? '--'}</h2><strong>Selon la date renseignée</strong></article>
        <article className="metric-card"><p>Préparation estimée</p><h2>{Math.round(data.readiness.score)}%</h2><strong>{data.readiness.certainty}</strong></article>
        <article className="metric-card"><p>Chapitres terminés</p><h2>{data.progression.chapters_completed}</h2><strong>{Math.round(data.progression.global)}% global</strong></article>
      </div>

      <RegionalNlpTools units={units} unitsMessage={unitsMessage} />

      <article className="panel-card">
        <div className="panel-title"><h2>Œuvres au programme importées</h2><p>{data.works.length}</p></div>
        {data.works.length ? data.works.map((work) => (
          <div className="history-item" key={work.id}>
            <span>{work.chapters_count}</span>
            <div>
              <strong>{work.title}</strong>
              <p>{work.author || 'Auteur fourni par le package'} - {work.genre || 'Genre non précisé'}</p>
            </div>
          </div>
        )) : <p>Aucune œuvre importée pour le moment.</p>}
      </article>

      <article className="panel-card">
        <div className="panel-title"><h2>Prochaine étape</h2><p>Guide</p></div>
        {data.study_path ? (
          <div className="history-item">
            <span>{Math.round(data.study_path.progress_percentage)}%</span>
            <div><strong>{data.study_path.title}</strong><p>Continuez votre parcours personnalisé.</p></div>
            <Link to={`/study-paths/${data.study_path.id}`}>Continuer</Link>
          </div>
        ) : data.next_mock_exam ? (
          <div className="history-item">
            <span>Test</span>
            <div><strong>{data.next_mock_exam.title}</strong><p>{data.next_mock_exam.status}</p></div>
            <Link to={`/assessments/${data.next_mock_exam.id}`}>Commencer</Link>
          </div>
        ) : <p>Aucune prochaine évaluation disponible.</p>}
      </article>

      <article className="panel-card">
        <div className="panel-title"><h2>Points faibles</h2><p>{data.weak_points.length}</p></div>
        {data.weak_points.length ? data.weak_points.map((point) => (
          <div className="history-item" key={point.assessment_id}>
            <span>{Math.round(point.score)}%</span>
            <div><strong>Évaluation {point.assessment_id}</strong><p>{point.message}</p></div>
          </div>
        )) : <p>Aucun point faible récent détecté.</p>}
      </article>
    </section>
  )
}

function RegionalNlpTools({ units, unitsMessage }) {
  const [activeTool, setActiveTool] = useState('exam')
  const workOptions = useMemo(() => {
    const byId = new Map()
    units.forEach((unit) => {
      if (unit.work_id && !byId.has(unit.work_id)) {
        byId.set(unit.work_id, unit.work_title || unit.work_id)
      }
    })
    return Array.from(byId.entries()).map(([id, title]) => ({ id, title }))
  }, [units])

  return (
    <article className="panel-card">
      <div className="panel-title">
        <h2>Outils NLP - régional français</h2>
        <p>{units.length ? `${units.length} unités pédagogiques disponibles` : unitsMessage || 'Chargement des unités...'}</p>
      </div>
      <div className="course-tabs">
        <button className={activeTool === 'exam' ? 'active' : ''} type="button" onClick={() => setActiveTool('exam')}>Consigne</button>
        <button className={activeTool === 'figure' ? 'active' : ''} type="button" onClick={() => setActiveTool('figure')}>Figures</button>
        <button className={activeTool === 'qa' ? 'active' : ''} type="button" onClick={() => setActiveTool('qa')}>Question</button>
        <button className={activeTool === 'adapt' ? 'active' : ''} type="button" onClick={() => setActiveTool('adapt')}>Adapter</button>
      </div>
      {activeTool === 'exam' && <ExamInstructionTool />}
      {activeTool === 'figure' && <FigureTool />}
      {activeTool === 'qa' && <QuestionTool units={units} workOptions={workOptions} />}
      {activeTool === 'adapt' && <AdaptationTool />}
    </article>
  )
}

function ExamInstructionTool() {
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  async function submit() {
    if (!text.trim()) {
      setError('Saisissez une consigne à analyser.')
      return
    }
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const [competence, level] = await Promise.all([
        classifyExamCompetence(text),
        predictLevel(text),
      ])
      setResult({ competence: competence.data, level: level.data })
    } catch (err) {
      setError(formatNlpError(err, 'Analyse impossible.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolCard title="Analyse d'une consigne d'examen" error={error}>
      <textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="Exemple : Expliquez la valeur symbolique de cette scène." rows={5} />
      <button className="primary-button" disabled={loading} type="button" onClick={submit}>{loading ? 'Analyse...' : 'Analyser la consigne'}</button>
      {result && (
        <div className="history-item">
          <span>NLP</span>
          <div>
            <strong>Compétence détectée : {displayValue(result.competence.competence)}</strong>
            <p>Niveau estimé : {displayValue(result.level.predicted_level)}</p>
            <p>Diagnostic automatique à valider par un enseignant.</p>
          </div>
        </div>
      )}
    </ToolCard>
  )
}

function FigureTool() {
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  async function submit() {
    if (!text.trim()) {
      setError('Saisissez une phrase ou un extrait court.')
      return
    }
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const response = await analyzeFigure(text)
      setResult(response.data)
    } catch (err) {
      setError(formatNlpError(err, 'Analyse de figure impossible.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolCard title="Figures de style" error={error}>
      <textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="Exemple : La nuit murmure à l'oreille d'Antigone." rows={4} />
      <button className="primary-button" disabled={loading} type="button" onClick={submit}>{loading ? 'Analyse...' : 'Analyser la figure'}</button>
      {result && (
        <div className="history-item">
          <span>{result.contains_figure ? 'Oui' : 'Non'}</span>
          <div>
            <strong>{result.contains_figure ? `Figure détectée : ${displayValue(result.figure_type)}` : 'Aucune figure détectée'}</strong>
            <p>Mode utilisé : {displayValue(result.mode)}</p>
            <p>Validation humaine recommandée.</p>
          </div>
        </div>
      )}
    </ToolCard>
  )
}

function QuestionTool({ units, workOptions }) {
  const [workId, setWorkId] = useState('')
  const [unitId, setUnitId] = useState('')
  const [level, setLevel] = useState('intermediaire')
  const [task, setTask] = useState('comprehension')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const filteredUnits = workId ? units.filter((unit) => unit.work_id === workId) : units

  useEffect(() => {
    if (!unitId && filteredUnits[0]) {
      setUnitId(filteredUnits[0].unit_id)
    }
  }, [filteredUnits, unitId])

  async function submit() {
    if (!unitId) {
      setError('Sélectionnez une unité pédagogique.')
      return
    }
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const response = await generateQuestionCorrection({ unit_id: unitId, task, level })
      setResult(response.data)
    } catch (err) {
      setError(formatNlpError(err, 'Génération impossible.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolCard title="Génération question/correction" error={error}>
      <div className="admin-form-row">
        <label>Œuvre
          <select value={workId} onChange={(event) => {
            setWorkId(event.target.value)
            setUnitId('')
          }}>
            <option value="">Toutes les œuvres</option>
            {workOptions.map((work) => <option key={work.id} value={work.id}>{work.title}</option>)}
          </select>
        </label>
        <label>Chapitre / séquence
          <select value={unitId} onChange={(event) => setUnitId(event.target.value)}>
            {filteredUnits.map((unit) => <option key={unit.unit_id} value={unit.unit_id}>{unit.unit_number}. {unit.unit_title}</option>)}
          </select>
        </label>
      </div>
      <div className="admin-form-row">
        <label>Niveau
          <select value={level} onChange={(event) => setLevel(event.target.value)}>
            {LEVELS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
        <label>Tâche
          <select value={task} onChange={(event) => setTask(event.target.value)}>
            {TASKS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
      </div>
      <button className="primary-button" disabled={loading || !unitId} type="button" onClick={submit}>{loading ? 'Génération...' : 'Générer'}</button>
      {result && (
        <div className="nlp-result-grid">
          <ResultBlock title="Question" text={result.question} />
          <ResultBlock title="Correction proposée" text={result.correction} />
          <ResultBlock title="Éléments de réponse" text={result.answer_elements} />
          <ResultBlock title="Barème" text={result.bareme} />
          <p>À valider par un enseignant.</p>
          <button className="secondary-button" type="button" onClick={() => copyText(result.question)}>Copier la question</button>
          <button className="secondary-button" type="button" onClick={() => copyText(result.correction)}>Copier la correction</button>
        </div>
      )}
    </ToolCard>
  )
}

function AdaptationTool() {
  const [sourceText, setSourceText] = useState('')
  const [sourceLevel, setSourceLevel] = useState('intermediaire')
  const [targetLevel, setTargetLevel] = useState('debutant')
  const [contentType, setContentType] = useState('explication')
  const [unitTitle, setUnitTitle] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  async function submit() {
    if (!sourceText.trim()) {
      setError('Saisissez un texte source.')
      return
    }
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const response = await adaptPedagogicalText({
        source_text: sourceText,
        source_level: sourceLevel,
        target_level: targetLevel,
        content_type: contentType,
        unit_title: unitTitle || 'Unité pédagogique',
        adaptation_id: `regional-${Date.now()}`,
      })
      setResult(response.data)
    } catch (err) {
      setError(formatNlpError(err, 'Adaptation impossible.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolCard title="Adaptation pédagogique" error={error}>
      <textarea value={sourceText} onChange={(event) => setSourceText(event.target.value)} placeholder="Collez ici le texte à adapter." rows={5} />
      <div className="admin-form-row">
        <label>Niveau source
          <select value={sourceLevel} onChange={(event) => setSourceLevel(event.target.value)}>
            {LEVELS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
        <label>Niveau cible
          <select value={targetLevel} onChange={(event) => setTargetLevel(event.target.value)}>
            {LEVELS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
      </div>
      <div className="admin-form-row">
        <label>Type de contenu
          <input value={contentType} onChange={(event) => setContentType(event.target.value)} />
        </label>
        <label>Titre de l'unité
          <input value={unitTitle} onChange={(event) => setUnitTitle(event.target.value)} placeholder="Antigone - scène clé" />
        </label>
      </div>
      <button className="primary-button" disabled={loading} type="button" onClick={submit}>{loading ? 'Adaptation...' : 'Adapter le texte'}</button>
      {result && (
        <div className="history-item">
          <span>NLP</span>
          <div>
            <strong>Texte adapté</strong>
            <p>{displayValue(result.adapted_text)}</p>
            <p>Opération utilisée : {displayValue(result.operation || result.mode)}</p>
            <p>Validation humaine recommandée.</p>
          </div>
        </div>
      )}
    </ToolCard>
  )
}

function ToolCard({ title, error, children }) {
  return (
    <div className="nlp-tool-panel">
      <h3>{title}</h3>
      {error && <p className="form-error">{error}</p>}
      {children}
    </div>
  )
}

function ResultBlock({ title, text }) {
  return (
    <div className="history-item">
      <span>{title.slice(0, 2)}</span>
      <div>
        <strong>{title}</strong>
        <p>{displayValue(text)}</p>
      </div>
    </div>
  )
}

function displayValue(value) {
  if (value === null || value === undefined || value === '') return '--'
  if (Array.isArray(value)) return value.join(', ')
  return String(value)
}

function copyText(value) {
  navigator.clipboard?.writeText(String(value || ''))
}

export default RegionalExamPreparationPage
