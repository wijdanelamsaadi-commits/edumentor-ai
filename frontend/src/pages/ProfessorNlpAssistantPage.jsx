import { useEffect, useMemo, useState } from 'react'
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

const CONTENT_TYPES = [
  { value: 'explication_detaillee', label: 'Explication détaillée' },
  { value: 'resume', label: 'Résumé' },
  { value: 'exercice', label: 'Exercice' },
  { value: 'correction', label: 'Correction' },
]

function ProfessorNlpAssistantPage() {
  const [activeTool, setActiveTool] = useState('exam')
  const [units, setUnits] = useState([])
  const [unitsMessage, setUnitsMessage] = useState('Chargement des unités...')

  useEffect(() => {
    let cancelled = false
    getNlpUnits()
      .then((response) => {
        if (cancelled) return
        const rows = Array.isArray(response.data?.units) ? response.data.units : []
        setUnits(rows)
        setUnitsMessage(`${rows.length} unités pédagogiques disponibles`)
      })
      .catch((error) => {
        if (!cancelled) {
          setUnits([])
          setUnitsMessage(formatNlpError(error, 'Unités pédagogiques indisponibles.'))
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  const workOptions = useMemo(() => buildWorkOptions(units), [units])

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Assistant de création pédagogique</h1>
        <p>Outils d'aide à la préparation des supports, questions et corrections pour le régional de français.</p>
      </div>

      <article className="panel-card">
        <div className="panel-title">
          <h2>Outils de préparation</h2>
          <p>{unitsMessage}</p>
        </div>
        <div className="course-tabs">
          <button className={activeTool === 'exam' ? 'active' : ''} type="button" onClick={() => setActiveTool('exam')}>Analyser une consigne</button>
          <button className={activeTool === 'figure' ? 'active' : ''} type="button" onClick={() => setActiveTool('figure')}>Analyser une figure de style</button>
          <button className={activeTool === 'qa' ? 'active' : ''} type="button" onClick={() => setActiveTool('qa')}>Générer une question et une correction</button>
          <button className={activeTool === 'adapt' ? 'active' : ''} type="button" onClick={() => setActiveTool('adapt')}>Adapter un contenu selon le niveau</button>
        </div>

        {activeTool === 'exam' && <ExamInstructionTool />}
        {activeTool === 'figure' && <FigureTool />}
        {activeTool === 'qa' && <QuestionTool units={units} workOptions={workOptions} />}
        {activeTool === 'adapt' && <AdaptationTool units={units} workOptions={workOptions} />}
      </article>
    </section>
  )
}

function ExamInstructionTool() {
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  function reset() {
    setText('')
    setResult(null)
    setError('')
  }

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
      setResult({
        competence: competence.data?.competence,
        level: level.data?.predicted_level,
      })
    } catch (err) {
      setError(formatNlpError(err, 'Analyse impossible.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolCard title="Analyser une consigne" error={error}>
      <textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="Exemple : Expliquez la valeur symbolique de cette scène." rows={5} />
      <button className="primary-button" disabled={loading} type="button" onClick={submit}>{loading ? 'Analyse...' : 'Analyser la consigne'}</button>
      {result && (
        <DraftResult onCopy={() => copyText(formatDraftResult(result))} onEdit={() => setResult(null)} onReset={reset}>
          <ResultBlock title="Compétence repérée" text={formatLabel(result.competence)} />
          <ResultBlock title="Niveau estimé" text={formatLabel(result.level)} />
        </DraftResult>
      )}
    </ToolCard>
  )
}

function FigureTool() {
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  function reset() {
    setText('')
    setResult(null)
    setError('')
  }

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
      setResult({
        contains_figure: response.data?.contains_figure,
        figure_type: response.data?.figure_type,
      })
    } catch (err) {
      setError(formatNlpError(err, 'Analyse de figure impossible.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolCard title="Analyser une figure de style" error={error}>
      <textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="Exemple : La nuit murmure à Antigone." rows={4} />
      <button className="primary-button" disabled={loading} type="button" onClick={submit}>{loading ? 'Analyse...' : 'Analyser la figure'}</button>
      {result && (
        <DraftResult onCopy={() => copyText(formatDraftResult(result))} onEdit={() => setResult(null)} onReset={reset}>
          <ResultBlock
            title={result.contains_figure ? 'Figure repérée' : 'Analyse proposée'}
            text={result.contains_figure ? formatLabel(result.figure_type) : 'Aucune figure de style évidente dans cet extrait.'}
          />
        </DraftResult>
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

  const filteredUnits = useMemo(
    () => (workId ? units.filter((unit) => unit.work_id === workId) : units),
    [units, workId],
  )
  const selectedUnit = filteredUnits.find((unit) => unit.unit_id === unitId) || filteredUnits[0]

  useEffect(() => {
    if (!filteredUnits.some((unit) => unit.unit_id === unitId)) {
      setUnitId(filteredUnits[0]?.unit_id || '')
    }
  }, [filteredUnits, unitId])

  function reset() {
    setResult(null)
    setError('')
  }

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
    <ToolCard title="Générer une question et une correction" error={error}>
      <UnitSelector
        filteredUnits={filteredUnits}
        selectedUnit={selectedUnit}
        unitId={unitId}
        workId={workId}
        workOptions={workOptions}
        onUnitChange={setUnitId}
        onWorkChange={(value) => {
          setWorkId(value)
          setUnitId('')
          reset()
        }}
      />
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
        <label>Titre de l'unité
          <input readOnly value={selectedUnit?.unit_title || ''} />
        </label>
      </div>
      <button className="primary-button" disabled={loading || !unitId} type="button" onClick={submit}>{loading ? 'Génération...' : 'Générer'}</button>
      {result && (
        <DraftResult onCopy={() => copyText(formatDraftResult(result))} onEdit={() => setResult(null)} onReset={reset}>
          <ResultBlock title="Question" text={result.question} />
          <ResultBlock title="Correction proposée" text={result.correction} />
          <ResultBlock title="Éléments de réponse" text={result.answer_elements} />
          <ResultBlock title="Barème" text={result.bareme} />
        </DraftResult>
      )}
    </ToolCard>
  )
}

function AdaptationTool({ units, workOptions }) {
  const [workId, setWorkId] = useState('')
  const [unitId, setUnitId] = useState('')
  const [sourceText, setSourceText] = useState('')
  const [sourceLevel, setSourceLevel] = useState('intermediaire')
  const [targetLevel, setTargetLevel] = useState('debutant')
  const [contentType, setContentType] = useState('explication_detaillee')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const filteredUnits = useMemo(
    () => (workId ? units.filter((unit) => unit.work_id === workId) : units),
    [units, workId],
  )
  const selectedUnit = filteredUnits.find((unit) => unit.unit_id === unitId) || filteredUnits[0]

  useEffect(() => {
    if (!filteredUnits.some((unit) => unit.unit_id === unitId)) {
      setUnitId(filteredUnits[0]?.unit_id || '')
    }
  }, [filteredUnits, unitId])

  function reset() {
    setSourceText('')
    setResult(null)
    setError('')
  }

  function editResult() {
    if (result?.adapted_text) {
      setSourceText(result.adapted_text)
      setResult(null)
    }
  }

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
        unit_title: selectedUnit?.unit_title || 'Antigone - scène clé',
      })
      setResult(response.data)
    } catch (err) {
      setError(formatNlpError(err, 'Adaptation impossible.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolCard title="Adapter un contenu selon le niveau" error={error}>
      <UnitSelector
        filteredUnits={filteredUnits}
        selectedUnit={selectedUnit}
        unitId={unitId}
        workId={workId}
        workOptions={workOptions}
        onUnitChange={setUnitId}
        onWorkChange={(value) => {
          setWorkId(value)
          setUnitId('')
          setResult(null)
        }}
      />
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
        <label>Type de contenu
          <select value={contentType} onChange={(event) => setContentType(event.target.value)}>
            {CONTENT_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
      </div>
      <button className="primary-button" disabled={loading} type="button" onClick={submit}>{loading ? 'Adaptation...' : 'Adapter le texte'}</button>
      {result && (
        <DraftResult onCopy={() => copyText(result.adapted_text)} onEdit={editResult} onReset={reset}>
          <ResultBlock title="Texte adapté" text={result.adapted_text} />
        </DraftResult>
      )}
    </ToolCard>
  )
}

function UnitSelector({ filteredUnits, onUnitChange, onWorkChange, selectedUnit, unitId, workId, workOptions }) {
  return (
    <div className="admin-form-row">
      <label>Œuvre
        <select value={workId} onChange={(event) => onWorkChange(event.target.value)}>
          <option value="">Toutes les œuvres</option>
          {workOptions.map((work) => <option key={work.id} value={work.id}>{work.title}</option>)}
        </select>
      </label>
      <label>Chapitre / séquence
        <select value={unitId} onChange={(event) => onUnitChange(event.target.value)}>
          {filteredUnits.map((unit) => <option key={unit.unit_id} value={unit.unit_id}>{unit.unit_number}. {unit.unit_title}</option>)}
        </select>
      </label>
      <label>Unité sélectionnée
        <input readOnly value={selectedUnit?.unit_title || ''} />
      </label>
    </div>
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

function DraftResult({ children, onCopy, onEdit, onReset }) {
  return (
    <div className="nlp-result-grid">
      <div className="history-item">
        <span>IA</span>
        <div>
          <strong>Brouillon IA</strong>
          <p>À vérifier par un enseignant avant utilisation avec les élèves.</p>
        </div>
      </div>
      {children}
      <div className="course-actions">
        <button className="secondary-button" type="button" onClick={onCopy}>Copier</button>
        <button className="secondary-button" type="button" onClick={onEdit}>Modifier</button>
        <button className="secondary-button" type="button" onClick={onReset}>Réinitialiser</button>
      </div>
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

function buildWorkOptions(units) {
  const byId = new Map()
  units.forEach((unit) => {
    if (unit.work_id && !byId.has(unit.work_id)) {
      byId.set(unit.work_id, unit.work_title || unit.work_id)
    }
  })
  return Array.from(byId.entries()).map(([id, title]) => ({ id, title }))
}

function formatLabel(value) {
  return displayValue(value).replace(/_/g, ' ')
}

function displayValue(value) {
  if (value === null || value === undefined || value === '') return '--'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') {
    return Object.entries(value)
      .filter(([, item]) => item !== null && item !== undefined && item !== '')
      .map(([key, item]) => `${formatLabel(key)} : ${displayValue(item)}`)
      .join(' | ')
  }
  return String(value)
}

function formatDraftResult(result) {
  if (!result || typeof result !== 'object') return ''
  return Object.entries(result)
    .filter(([key]) => ![
      'model_version',
      'decision_scores',
      'decision_margin',
      'style_reference',
      'adaptation_id',
      'mode',
      'requires_human_validation',
    ].includes(key))
    .map(([key, value]) => `${formatLabel(key)} : ${displayValue(value)}`)
    .join('\n')
}

function copyText(value) {
  navigator.clipboard?.writeText(String(value || ''))
}

export default ProfessorNlpAssistantPage
