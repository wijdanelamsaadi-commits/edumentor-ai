import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  BarChart3,
  BookOpen,
  Calendar,
  ChevronRight,
  Clock3,
  ClipboardCheck,
  FileText,
  ListChecks,
  MapPin,
  Search,
  ShieldCheck,
  Target,
  TrendingUp,
} from 'lucide-react'
import { getRegionalExamPreparation, getRegionalExams } from '../services/api.js'

const EMPTY_REGIONAL_MESSAGE = "Aucun examen régional n'est encore disponible. Continuez vos cours et exercices en attendant une nouvelle évaluation."

const DEFAULT_FILTERS = {
  year: '',
  region: '',
  work_id: '',
  session: '',
  status: '',
  search: '',
}

function RegionalExamPreparationPage() {
  const [preparation, setPreparation] = useState(null)
  const [examData, setExamData] = useState(null)
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [selectedSkill, setSelectedSkill] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      getRegionalExamPreparation(),
      getRegionalExams(cleanFilters(filters)),
    ])
      .then(([regionalPreparation, exams]) => {
        if (cancelled) return
        setPreparation(regionalPreparation)
        setExamData(exams)
        setMessage('')
      })
      .catch((error) => {
        if (!cancelled) {
          setMessage(error?.message || 'Préparation régionale indisponible.')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [filters])

  const exams = Array.isArray(examData?.exams) ? examData.exams : []
  const stats = examData?.stats || preparation?.regional_exam_stats || {}
  const options = examData?.filters || {}
  const works = useMemo(() => (
    Array.isArray(preparation?.works) ? preparation.works : []
  ), [preparation?.works])
  const weakPoints = Array.isArray(preparation?.weak_points) ? preparation.weak_points : []
  const progression = preparation?.progression || {}
  const readiness = preparation?.readiness || {}
  const weaknessPrediction = preparation?.weakness_prediction || {}
  const weaknessCompetencies = Array.isArray(weaknessPrediction?.competencies)
    ? weaknessPrediction.competencies
    : []

  const workOptions = useMemo(() => {
    const fromExams = Array.isArray(options.works)
      ? options.works.map((item) => ({ id: item[0] || item[1], title: item[1] || item[0] })).filter((item) => item.id)
      : []
    if (fromExams.length) return fromExams
    return works.map((work) => ({ id: work.id, title: work.title }))
  }, [options.works, works])

  const topStats = [
    {
      icon: ClipboardCheck,
      tone: 'red',
      label: 'Examens disponibles',
      value: stats.total_exams || 0,
      hint: `${stats.completed_exams || 0} terminé(s)`,
    },
    {
      icon: Clock3,
      tone: 'blue',
      label: 'Préparation estimée',
      value: `${Math.round(Number(readiness.score || 0))}%`,
      hint: readiness.certainty || 'Non prédictif',
      progress: Math.round(Number(readiness.score || 0)),
    },
    {
      icon: TrendingUp,
      tone: 'green',
      label: 'Meilleur score',
      value: stats.best_score === null || stats.best_score === undefined ? '--' : `${Math.round(Number(stats.best_score))}%`,
      hint: `${stats.attempts_count || 0} tentative(s)`,
      progress: stats.best_score === null || stats.best_score === undefined ? 0 : Math.round(Number(stats.best_score)),
    },
    {
      icon: BookOpen,
      tone: 'purple',
      label: 'Chapitres terminés',
      value: progression.chapters_completed || 0,
      hint: `${Math.round(Number(progression.global || 0))}% global`,
      progress: Math.round(Number(progression.global || 0)),
    },
  ]

  return (
    <section className="regional-prep-page">
      <div className="regional-prep-heading">
        <h1>Préparation au régional de français</h1>
        <p>1ère Bac Maroc - examens, entraînements et suivi de progression.</p>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <div className="regional-prep-stats">
        {topStats.map((item) => <RegionalStatCard key={item.label} {...item} />)}
      </div>

      <div className="regional-prep-layout">
        <article className="regional-exam-list-panel">
          <header className="regional-panel-heading">
            <div>
              <h2>Examens disponibles</h2>
              <span>{stats.total_exams || exams.length}</span>
            </div>
            <p>{loading ? 'Chargement...' : `${exams.length} résultat(s)`}</p>
          </header>

          <RegionalExamFilters
            filters={filters}
            options={options}
            setFilters={setFilters}
            workOptions={workOptions}
          />

          {loading ? (
            <p className="regional-empty-state">Chargement...</p>
          ) : exams.length ? (
            <div className="regional-exam-list">
              {exams.map((exam) => <RegionalExamRow exam={exam} key={exam.id} />)}
            </div>
          ) : <p className="regional-empty-state">{EMPTY_REGIONAL_MESSAGE}</p>}
        </article>

        <aside className="regional-side-column" aria-label="Informations complémentaires">
          <WorksCard works={works} />
          <WeakPointsCard onOpenSkill={setSelectedSkill} weakPoints={weakPoints} />
          <PersonalizedAnalysisCard
            onOpenSkill={setSelectedSkill}
            skills={weaknessCompetencies}
          />
        </aside>
      </div>

      {selectedSkill && (
        <SkillDetailDialog onClose={() => setSelectedSkill(null)} skill={selectedSkill} />
      )}
    </section>
  )
}

function RegionalStatCard({ hint, icon: Icon, label, progress, tone, value }) {
  return (
    <article className={`regional-prep-stat ${tone}`}>
      <span><Icon size={28} /></span>
      <div>
        <p>{label}</p>
        <h2>{value}</h2>
        <strong>{hint}</strong>
        {typeof progress === 'number' && (
          <div className="regional-prep-stat-track" aria-label={`${label} ${progress}%`}>
            <i style={{ width: `${Math.min(100, Math.max(0, progress))}%` }} />
          </div>
        )}
      </div>
    </article>
  )
}

function RegionalExamFilters({ filters, options, setFilters, workOptions }) {
  return (
    <div className="regional-filter-bar">
      <label className="regional-search-field">
        <Search size={18} />
        <input
          aria-label="Rechercher un examen régional"
          value={filters.search}
          onChange={(event) => updateFilter(setFilters, 'search', event.target.value)}
          placeholder="Titre, œuvre, région..."
        />
      </label>
      <SelectFilter label="Année" name="year" options={options.years} value={filters.year} onChange={setFilters} />
      <SelectFilter label="Région" name="region" options={options.regions} value={filters.region} onChange={setFilters} />
      <label className="regional-select-field">Œuvre
        <select value={filters.work_id} onChange={(event) => updateFilter(setFilters, 'work_id', event.target.value)}>
          <option value="">Toutes</option>
          {workOptions.map((work) => <option key={`${work.id}-${work.title}`} value={work.id}>{work.title}</option>)}
        </select>
      </label>
      <SelectFilter label="Session" name="session" options={options.sessions} value={filters.session} onChange={setFilters} />
      <SelectFilter label="Statut" name="status" options={options.statuses} value={filters.status} onChange={setFilters} />
    </div>
  )
}

function RegionalExamRow({ exam }) {
  const completed = exam.status === 'terminé' || exam.status === 'completed' || Number(exam.best_score || 0) > 0
  return (
    <article className="regional-exam-row">
      <div className={`regional-exam-status ${completed ? 'completed' : ''}`}>
        <ShieldCheck size={19} />
        <strong>Officiel vérifié</strong>
        <span>{completed ? 'terminé' : 'non commencé'}</span>
      </div>
      <div className="regional-exam-main">
        <h3>{exam.title}</h3>
        <p>{exam.work_title || exam.description || 'Sujet de préparation régional.'}</p>
        <div className="regional-exam-meta">
          <span><Calendar size={15} />{exam.year || '--'}</span>
          <span><MapPin size={15} />{exam.region || '--'}</span>
          <span><Clock3 size={15} />{exam.duration_minutes ? `${exam.duration_minutes} min` : '--'}</span>
          <span><BarChart3 size={15} />{exam.total_points || 0} pts</span>
          <span><ListChecks size={15} />{exam.question_count || 0} questions</span>
        </div>
      </div>
      <div className="regional-exam-score">
        <span>Meilleur score</span>
        <strong>{exam.best_score === null || exam.best_score === undefined ? '--' : `${Math.round(Number(exam.best_score))}%`}</strong>
      </div>
      <Link className={completed ? 'regional-open-exam primary' : 'regional-open-exam'} to={`/regional-exam-preparation/${exam.id}`}>Ouvrir l'examen</Link>
    </article>
  )
}

function WorksCard({ works }) {
  return (
    <article className="regional-side-card">
      <header>
        <div><BookOpen size={22} /><h2>Œuvres au programme</h2></div>
        <span>{works.length}</span>
      </header>
      {works.length ? (
        <div className="regional-work-list">
          {works.map((work) => (
            <div className="regional-work-item" key={work.id}>
              <span>{work.chapters_count || 0}</span>
              <div>
                <strong>{work.title}</strong>
                <p>{work.author || 'Auteur fourni par le package'} - {work.genre || 'Genre non précisé'}</p>
              </div>
            </div>
          ))}
        </div>
      ) : <p className="regional-empty-state">Aucune œuvre importée pour le moment.</p>}
    </article>
  )
}

function WeakPointsCard({ onOpenSkill, weakPoints }) {
  return (
    <article className="regional-side-card">
      <header>
        <div><Target size={22} /><h2>Points faibles</h2></div>
        <span>{weakPoints.length}</span>
      </header>
      {weakPoints.length ? (
        <div className="regional-weak-skill-list">
          {weakPoints.map((point) => (
            <WeakSkillCard key={`${point.assessment_id}-${point.competence || point.message}`} onOpen={onOpenSkill} skill={normalizeWeakPoint(point)} />
          ))}
        </div>
      ) : <p className="regional-empty-state">Aucun point faible récent détecté.</p>}
    </article>
  )
}

function WeakSkillCard({ onOpen, skill }) {
  const score = Number.isFinite(Number(skill.score)) ? Math.round(Number(skill.score)) : 0
  return (
    <button
      aria-label={`Voir le détail de ${skill.competence}`}
      className="regional-weak-skill"
      onClick={() => onOpen(skill)}
      type="button"
    >
      <span className="regional-score-ring" style={{ '--score': `${score}%` }}>{score}%</span>
      <div>
        <strong>{skill.competence}</strong>
        <p>{skill.recommendation}</p>
      </div>
      <ChevronRight size={18} />
    </button>
  )
}

function PersonalizedAnalysisCard({ onOpenSkill, skills }) {
  return (
    <article className="regional-side-card regional-personal-analysis">
      <header>
        <div><FileText size={22} /><h2>Analyse personnalisée des compétences</h2></div>
      </header>
      <p>Découvrez votre niveau dans chaque compétence et suivez votre progression.</p>
      {skills.length ? (
        <div className="regional-personal-skill-list">
          {skills.map((skill) => (
            <PersonalizedSkillRow key={skill.competence} onOpen={onOpenSkill} skill={normalizeSkillPrediction(skill)} />
          ))}
        </div>
      ) : <p className="regional-empty-state">Aucune donnée d'apprentissage disponible pour le moment.</p>}
      <button className="regional-analysis-button" disabled={!skills.length} onClick={() => skills[0] && onOpenSkill(normalizeSkillPrediction(skills[0]))} type="button">
        Voir mon analyse détaillée
      </button>
    </article>
  )
}

function PersonalizedSkillRow({ onOpen, skill }) {
  return (
    <button
      aria-label={`Ouvrir l'analyse de ${skill.competence}`}
      className="regional-personal-skill"
      onClick={() => onOpen(skill)}
      type="button"
    >
      <div>
        <strong>{skill.competence}</strong>
        <p>{skill.recommendation}</p>
      </div>
      <div>
        <span>{skill.status}</span>
        <b>{skill.scoreLabel}</b>
        <small>{skill.trendLabel}</small>
      </div>
      <ChevronRight size={18} />
    </button>
  )
}

function SkillDetailDialog({ onClose, skill }) {
  return (
    <div className="regional-analysis-modal" onMouseDown={onClose} role="presentation">
      <section aria-labelledby="regional-skill-title" aria-modal="true" className="regional-analysis-dialog" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <header>
          <div>
            <span><Target size={24} /></span>
            <div>
              <h2 id="regional-skill-title">{skill.competence}</h2>
              <p>{skill.status || 'Non évalué'} · {skill.scoreLabel || `${Math.round(Number(skill.score || 0))}%`}</p>
            </div>
          </div>
          <button aria-label="Fermer l'analyse détaillée" onClick={onClose} type="button">×</button>
        </header>
        <div className="regional-analysis-detail-grid">
          <DetailBox label="Progression" value={skill.trendLabel || 'Stable'} />
          <DetailBox label="Score moyen" value={skill.scoreLabel || `${Math.round(Number(skill.score || 0))}%`} />
          <DetailBox label="Niveau" value={skill.status || 'Non évalué'} />
        </div>
        <div className="regional-analysis-sections">
          <section>
            <h3>Recommandation</h3>
            <p>{skill.recommendation || 'Continuez les exercices ciblés pour renforcer cette compétence.'}</p>
          </section>
          <section>
            <h3>Exercices conseillés</h3>
            <p>{skill.exercises || 'Refaire les questions liées à cette compétence et comparer votre réponse à la correction.'}</p>
          </section>
          <section>
            <h3>Points à améliorer</h3>
            <p>{skill.improvement || skill.message || 'Relire la consigne, identifier les éléments attendus puis justifier chaque réponse.'}</p>
          </section>
        </div>
      </section>
    </div>
  )
}

function DetailBox({ label, value }) {
  return <div><span>{label}</span><strong>{value}</strong></div>
}

function SelectFilter({ label, name, onChange, options = [], value }) {
  return (
    <label className="regional-select-field">{label}
      <select value={value} onChange={(event) => updateFilter(onChange, name, event.target.value)}>
        <option value="">Tous</option>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  )
}

function normalizeWeakPoint(point) {
  return {
    competence: point.competence || `Évaluation ${point.assessment_id}`,
    score: point.score,
    scoreLabel: `${Math.round(Number(point.score || 0))}%`,
    status: scoreToStatus(point.score),
    trendLabel: 'À suivre',
    recommendation: point.message || 'Revoir les exercices ciblés avant la prochaine tentative.',
    message: point.message,
  }
}

function normalizeSkillPrediction(item) {
  const score = item.score_percentage === null || item.score_percentage === undefined ? null : Math.round(Number(item.score_percentage))
  return {
    competence: item.competence,
    score,
    scoreLabel: score === null ? '--' : `${score}%`,
    status: item.label || scoreToStatus(score),
    trendLabel: item.trend_percentage ? `${item.trend_percentage > 0 ? '+' : ''}${Math.round(Number(item.trend_percentage))}%` : 'Stable',
    recommendation: item.recommendation || 'Continuer les entraînements ciblés.',
    exercises: item.suggested_exercises || item.exercise_recommendation,
    improvement: item.improvement_area,
  }
}

function scoreToStatus(value) {
  const score = Number(value)
  if (!Number.isFinite(score)) return 'Non évalué'
  if (score < 50) return 'Faible'
  if (score < 75) return 'À renforcer'
  return 'Maîtrisé'
}

function updateFilter(setFilters, key, value) {
  setFilters((current) => ({ ...current, [key]: value }))
}

function cleanFilters(filters) {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value))
}

export default RegionalExamPreparationPage
