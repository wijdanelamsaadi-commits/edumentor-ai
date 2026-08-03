import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Circle,
  Clock3,
  Dumbbell,
  LockKeyhole,
  MessageCircleQuestion,
  Play,
  RefreshCw,
  SkipForward,
  Sparkles,
  Target,
  Trophy,
} from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  completeStudyPathItem,
  getStudyPath,
  refreshStudyPath,
  skipStudyPathItem,
  startStudyPathItem,
} from '../services/api.js'
import './StudyPathPage.css'

function StudyPathPage() {
  const { pathId } = useParams()
  const navigate = useNavigate()
  const [path, setPath] = useState(null)
  const [message, setMessage] = useState('')
  const [messageType, setMessageType] = useState('info')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [busyItemId, setBusyItemId] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setMessage('')

    try {
      setPath(await getStudyPath(pathId))
    } catch (error) {
      setMessageType('error')
      setMessage(error.message || 'Parcours indisponible.')
    } finally {
      setLoading(false)
    }
  }, [pathId])

  useEffect(() => {
    load()
  }, [load])

  const items = useMemo(() => path?.items || [], [path])
  const current = path?.current_item || null
  const progress = Math.round(Number(path?.progress_percentage || 0))

  const statusCounts = useMemo(() => {
    const counts = {
      completed: 0,
      available: 0,
      in_progress: 0,
      locked: 0,
      skipped: 0,
    }

    items.forEach((item) => {
      if (counts[item.status] !== undefined) {
        counts[item.status] += 1
      }
    })

    return counts
  }, [items])

  async function start(item) {
    if (!item || busyItemId) return

    setBusyItemId(item.id)
    setMessage('')

    try {
      const updated = await startStudyPathItem(pathId, item.id)
      setPath(updated)

      if (item.route) {
        navigate(item.route)
      }
    } catch (error) {
      setMessageType('error')
      setMessage(error.message || 'Cette étape est indisponible.')
    } finally {
      setBusyItemId(null)
    }
  }

  async function complete(item) {
    if (!item || busyItemId) return

    setBusyItemId(item.id)
    setMessage('')

    try {
      const updated = await completeStudyPathItem(pathId, item.id)
      setPath(updated)
      setMessageType('success')
      setMessage('Étape terminée. La prochaine étape disponible a été déverrouillée.')
    } catch (error) {
      setMessageType('error')
      setMessage(error.message || 'Impossible de terminer cette étape.')
    } finally {
      setBusyItemId(null)
    }
  }

  async function skip(item) {
    if (!item || busyItemId) return

    setBusyItemId(item.id)
    setMessage('')

    try {
      const updated = await skipStudyPathItem(pathId, item.id)
      setPath(updated)
      setMessageType('success')
      setMessage('Étape facultative ignorée.')
    } catch (error) {
      setMessageType('error')
      setMessage(error.message || "Impossible d'ignorer cette étape.")
    } finally {
      setBusyItemId(null)
    }
  }

  async function refresh() {
    if (refreshing) return

    setRefreshing(true)
    setMessage('')

    try {
      setPath(await refreshStudyPath(pathId))
      setMessageType('success')
      setMessage('Votre parcours a été actualisé.')
    } catch (error) {
      setMessageType('error')
      setMessage(error.message || 'Actualisation impossible.')
    } finally {
      setRefreshing(false)
    }
  }

  if (loading) {
    return (
      <section className="page-section study-path-page">
        <div className="study-path-state-card">
          <span className="study-path-spinner" />
          <h2>Chargement de votre parcours...</h2>
          <p>Nous préparons vos étapes personnalisées.</p>
        </div>
      </section>
    )
  }

  if (!path) {
    return (
      <section className="page-section study-path-page">
        <div className="study-path-state-card">
          <LockKeyhole size={42} />
          <h2>Parcours introuvable</h2>
          <p>{message || 'Ce parcours ne peut pas être affiché.'}</p>
          <button className="study-path-primary-button" onClick={() => navigate('/dashboard')} type="button">
            Retour au tableau de bord
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className="page-section study-path-page">
      <header className="study-path-page-header">
        <button className="study-path-back-button" onClick={() => navigate('/dashboard')} type="button">
          <ArrowLeft size={18} />
          Tableau de bord
        </button>

        <button className="study-path-refresh-button" disabled={refreshing} onClick={refresh} type="button">
          <RefreshCw className={refreshing ? 'rotating' : ''} size={18} />
          {refreshing ? 'Actualisation...' : 'Actualiser'}
        </button>
      </header>

      {message && (
        <div className={`study-path-message study-path-message--${messageType}`}>
          {messageType === 'success' ? <CheckCircle2 size={19} /> : <Circle size={19} />}
          <span>{message}</span>
        </div>
      )}

      <article className="study-path-hero">
        <div className="study-path-hero__content">
          <span className="study-path-eyebrow">
            <Sparkles size={16} />
            Parcours pédagogique personnalisé
          </span>

          <h1>{path.course_title || path.title}</h1>
          <p className="study-path-reason">{path.reason}</p>

          <div className="study-path-tags">
            <span><BookOpen size={16} />{path.subject_name || 'Français'}</span>
            <span><Target size={16} />Niveau adapté</span>
            <span><Clock3 size={16} />{path.progress?.estimated_remaining_steps || 0} étape(s) restante(s)</span>
          </div>
        </div>

        <div className="study-path-hero__progress">
          <div className="study-path-progress-ring" style={{ '--progress': `${progress * 3.6}deg` }}>
            <div>
              <strong>{progress}%</strong>
              <span>progression</span>
            </div>
          </div>

          <button
            className="study-path-primary-button"
            disabled={!current || current.status === 'locked' || Boolean(busyItemId)}
            onClick={() => start(current)}
            type="button"
          >
            <Play size={18} />
            {current ? 'Continuer mon parcours' : 'Parcours terminé'}
          </button>
        </div>
      </article>

      <div className="study-path-metrics">
        <MetricCard
          icon={CheckCircle2}
          label="Étapes terminées"
          value={`${path.progress?.completed_items || 0}/${path.progress?.required_items || 0}`}
          help="Étapes obligatoires"
        />
        <MetricCard
          icon={Target}
          label="Étape actuelle"
          value={current ? `N° ${current.order_index}` : '--'}
          help={current?.title || 'Aucune étape en attente'}
        />
        <MetricCard
          icon={Trophy}
          label="Statut"
          value={statusLabel(path.status)}
          help={path.status === 'completed' ? 'Objectif atteint' : 'Parcours en cours'}
        />
        <MetricCard
          icon={LockKeyhole}
          label="Étapes verrouillées"
          value={statusCounts.locked}
          help="Déverrouillées progressivement"
        />
      </div>

      {current && (
        <article className="study-path-current-card">
          <div className="study-path-current-card__icon">
            {iconForType(current.item_type, 27)}
          </div>

          <div className="study-path-current-card__copy">
            <span>Prochaine action recommandée</span>
            <h2>{current.title}</h2>
            <p>{current.description || current.reason}</p>
          </div>

          <button
            className="study-path-primary-button"
            disabled={current.status === 'locked' || Boolean(busyItemId)}
            onClick={() => start(current)}
            type="button"
          >
            {busyItemId === current.id ? 'Ouverture...' : 'Commencer'}
            <ChevronRight size={18} />
          </button>
        </article>
      )}

      <article className="study-path-timeline-card">
        <div className="study-path-section-title">
          <div>
            <span>Votre feuille de route</span>
            <h2>Les étapes du parcours</h2>
          </div>
          <strong>{items.length} étape(s)</strong>
        </div>

        <div className="study-path-timeline">
          {items.map((item, index) => (
            <StudyPathItem
              busy={busyItemId === item.id}
              isLast={index === items.length - 1}
              item={item}
              key={item.id}
              onComplete={complete}
              onOpen={start}
              onSkip={skip}
            />
          ))}
        </div>
      </article>
    </section>
  )
}

function MetricCard({ icon: Icon, label, value, help }) {
  return (
    <article className="study-path-metric-card">
      <span><Icon size={21} /></span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        <p>{help}</p>
      </div>
    </article>
  )
}

function StudyPathItem({ busy, isLast, item, onComplete, onOpen, onSkip }) {
  const locked = item.status === 'locked'
  const completed = item.status === 'completed'
  const skipped = item.status === 'skipped'
  const active = item.status === 'available' || item.status === 'in_progress'

  return (
    <div className={`study-path-step study-path-step--${item.status}`}>
      <div className="study-path-step__rail">
        <span className="study-path-step__marker">
          {completed ? <CheckCircle2 size={22} /> : locked ? <LockKeyhole size={18} /> : item.order_index}
        </span>
        {!isLast && <span className="study-path-step__line" />}
      </div>

      <article className="study-path-step__card">
        <div className="study-path-step__header">
          <div className="study-path-step__type">
            {iconForType(item.item_type, 19)}
            <span>{labelType(item.item_type)}</span>
          </div>
          <span className={`study-path-status study-path-status--${item.status}`}>
            {statusLabel(item.status)}
          </span>
        </div>

        <h3>{item.title}</h3>
        <p>{item.description || 'Étape de votre parcours personnalisé.'}</p>

        {item.reason && (
          <div className="study-path-step__reason">
            <Target size={16} />
            <span>{item.reason}</span>
          </div>
        )}

        <div className="study-path-step__footer">
          <span className="study-path-required-label">
            {item.required ? 'Étape obligatoire' : 'Étape facultative'}
          </span>

          <div className="study-path-step__actions">
            {active && item.route && (
              <button
                className="study-path-secondary-button"
                disabled={busy}
                onClick={() => onOpen(item)}
                type="button"
              >
                <Play size={16} />
                {busy ? 'Ouverture...' : 'Ouvrir'}
              </button>
            )}

            {active && (
              <button
                className="study-path-primary-button study-path-primary-button--compact"
                disabled={busy}
                onClick={() => onComplete(item)}
                type="button"
              >
                <CheckCircle2 size={16} />
                {busy ? 'Traitement...' : 'Marquer comme terminée'}
              </button>
            )}

            {!item.required && active && (
              <button
                className="study-path-skip-button"
                disabled={busy}
                onClick={() => onSkip(item)}
                type="button"
              >
                <SkipForward size={16} />
                Ignorer
              </button>
            )}

            {locked && (
              <span className="study-path-locked-copy">
                <LockKeyhole size={15} />
                Terminez l’étape précédente
              </span>
            )}

            {(completed || skipped) && (
              <span className="study-path-finished-copy">
                {completed ? <CheckCircle2 size={16} /> : <SkipForward size={16} />}
                {completed ? 'Étape terminée' : 'Étape ignorée'}
              </span>
            )}
          </div>
        </div>
      </article>
    </div>
  )
}

function iconForType(type, size = 18) {
  const props = { size }

  const icons = {
    review_chapter: <BookOpen {...props} />,
    personalized_lesson: <Sparkles {...props} />,
    knowledge_check: <Target {...props} />,
    exercise: <Dumbbell {...props} />,
    ask_chatbot: <MessageCircleQuestion {...props} />,
    personalized_assessment: <Trophy {...props} />,
    view_comparison: <Target {...props} />,
    continue_course: <ChevronRight {...props} />,
    start_recommended_course: <BookOpen {...props} />,
  }

  return icons[type] || <Circle {...props} />
}

function labelType(type) {
  const labels = {
    review_chapter: 'Révision du chapitre',
    personalized_lesson: 'Mini-cours personnalisé',
    knowledge_check: 'Vérification des acquis',
    exercise: 'Exercices pratiques',
    ask_chatbot: 'Aide du chatbot',
    personalized_assessment: 'Test personnalisé',
    view_comparison: 'Comparaison des résultats',
    continue_course: 'Cours suivant',
    start_recommended_course: 'Cours recommandé',
  }

  return labels[type] || 'Étape pédagogique'
}

function statusLabel(status) {
  const labels = {
    active: 'Actif',
    paused: 'En pause',
    completed: 'Terminée',
    archived: 'Archivé',
    locked: 'Verrouillée',
    available: 'Disponible',
    in_progress: 'En cours',
    skipped: 'Ignorée',
  }

  return labels[status] || status
}

export default StudyPathPage
