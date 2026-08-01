import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  compareRemediationPlan,
  completeRemediationItem,
  createPersonalizedAssessment,
  generateRemediationLessons,
  getRemediationPlan,
} from '../services/api.js'

function RemediationPage() {
  const { planId } = useParams()
  const [plan, setPlan] = useState(null)
  const [comparison, setComparison] = useState(null)
  const [message, setMessage] = useState('')
  const [generatingLessons, setGeneratingLessons] = useState(false)

  const refresh = useCallback(() => {
    Promise.allSettled([getRemediationPlan(planId), compareRemediationPlan(planId)])
      .then(([planResult, comparisonResult]) => {
        if (planResult.status === 'fulfilled') {
          setPlan(planResult.value)
        } else {
          setMessage(planResult.reason?.message || 'Parcours indisponible.')
        }
        if (comparisonResult.status === 'fulfilled') {
          setComparison(comparisonResult.value)
        }
      })
      .catch((err) => setMessage(err.message || 'Parcours indisponible.'))
  }, [planId])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function completeItem(itemId) {
    try {
      const updated = await completeRemediationItem(planId, itemId)
      setPlan(updated)
    } catch (err) {
      setMessage(err.message || 'Mise a jour impossible.')
    }
  }

  async function generateLessons() {
    try {
      setGeneratingLessons(true)
      const result = await generateRemediationLessons(planId)
      setMessage(result.lessons?.length ? 'Mini-cours personnalises prets.' : 'Aucun mini-cours supplementaire a generer.')
      refresh()
    } catch (err) {
      setMessage(err.message || 'Generation des mini-cours impossible.')
    } finally {
      setGeneratingLessons(false)
    }
  }

  async function createTest() {
    try {
      const assessment = await createPersonalizedAssessment(planId)
      if (assessment.status === 'published') {
        setMessage(`Test personnalise pret : ${assessment.title}`)
      } else {
        setMessage(`Test personnalise genere en brouillon : ${assessment.title}. Il sera disponible apres validation.`)
      }
    } catch (err) {
      setMessage(err.message || 'Creation du test impossible.')
    }
  }

  if (!plan) {
    return <section className="page-section dashboard-page"><article className="panel-card"><p>{message || 'Chargement...'}</p></article></section>
  }

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Parcours personnalise</h1>
          <p>{plan.course_title} - resultat initial {Math.round(plan.initial_score)}%</p>
        </div>
        <div className="admin-actions">
          <Link className="outline-button" to="/assessments">Mes evaluations</Link>
          <Link className="outline-button" to={`/remediation/${planId}/comparison`}>Comparaison</Link>
        </div>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <article className="continue-card">
        <div>
          <h2>Progression du parcours</h2>
          <p>Les etapes sont generees depuis les reponses incorrectes, les chapitres faibles et les competences liees.</p>
          <div className="inline-progress">
            <div className="progress-track"><span style={{ width: `${plan.progress}%` }} /></div>
            <strong>{Math.round(plan.progress)}%</strong>
          </div>
          {plan.next_step && <p>Prochaine action : {nextStepLabel(plan.next_step)}</p>}
          <p>Le test final cible les competences faibles, les chapitres a renforcer et les mini-cours termines.</p>
        </div>
        <div className="admin-actions">
          <button className="outline-button" disabled={generatingLessons} onClick={generateLessons} type="button">
            {generatingLessons ? 'Generation en cours...' : 'Generer les mini-cours'}
          </button>
          <button className="primary-button" disabled={plan.progress < 100} onClick={createTest} type="button">Passer le test personnalise</button>
        </div>
      </article>

      <article className="panel-card">
        <div className="panel-title"><h2>Mini-cours personnalises</h2><p>{plan.personalized_lessons?.length || 0}</p></div>
        {(plan.personalized_lessons || []).length ? plan.personalized_lessons.map((lesson) => (
          <div className="history-item" key={lesson.id}>
            <span>{lesson.status === 'completed' ? '✓' : lesson.id}</span>
            <div>
              <strong>{lesson.title}</strong>
              <p>{lesson.objective}</p>
              <small>{lesson.skill_name || lesson.chapter_title || 'Notion ciblee'} - {lesson.status}</small>
            </div>
            <Link className="primary-button" to={`/personalized-lessons/${lesson.id}`}>
              {lesson.status === 'completed' ? 'Revoir' : 'Commencer'}
            </Link>
          </div>
        )) : (
          <div className="admin-empty">
            <p>Aucun mini-cours personnalise genere pour ce parcours.</p>
            <button className="outline-button" disabled={generatingLessons} onClick={generateLessons} type="button">
              {generatingLessons ? 'Generation en cours...' : 'Generer maintenant'}
            </button>
          </div>
        )}
      </article>

      <article className="panel-card">
        <div className="panel-title"><h2>Comparaison avant / apres</h2><p>{comparison?.available ? 'Calcul reel' : 'En attente'}</p></div>
        {comparison?.available ? (
          <div className="dashboard-stats">
            <div className="metric-card"><p>Score initial</p><h2>{Math.round(comparison.initial_score)}%</h2></div>
            <div className="metric-card"><p>Score personnalise</p><h2>{Math.round(comparison.personalized_score)}%</h2></div>
            <div className="metric-card"><p>Variation</p><h2>{Math.round(comparison.variation_points)} pts</h2></div>
          </div>
        ) : (
          <p className="admin-empty">{comparison?.message || "Aucun deuxieme test n'existe encore pour ce parcours."}</p>
        )}
      </article>

      <article className="panel-card">
        <div className="panel-title"><h2>Etapes ciblees</h2><p>{plan.items?.length || 0}</p></div>
        {(plan.items || []).map((item) => (
          <div className="history-item" key={item.id}>
            <span>{item.completed ? '✓' : item.order_index}</span>
            <div>
              <strong>{labelType(item.item_type)} - {item.chapter_title || item.skill_name || 'Notion ciblee'}</strong>
              <p>{item.reason}</p>
              {item.personalized_lesson_id && <Link className="outline-button" to={`/personalized-lessons/${item.personalized_lesson_id}`}>Ouvrir le mini-cours</Link>}
              {item.item_type === 'chatbot_context' && <Link className="outline-button" to={`/chatbot?course_id=${plan.course_id}&chapter_id=${item.chapter_id || ''}`}>Ouvrir le chatbot contextualise</Link>}
            </div>
            <button disabled={item.completed} onClick={() => completeItem(item.id)} type="button">{item.completed ? 'Termine' : 'Marquer comme termine'}</button>
          </div>
        ))}
      </article>
    </section>
  )
}

function nextStepLabel(step) {
  if (!step) return 'Continuer le parcours'
  if (step.type === 'lesson') return `Lire ${step.title}`
  if (step.type === 'personalized_assessment') return 'Passer le test personnalise'
  return step.title || 'Continuer le parcours'
}

function labelType(type) {
  const labels = {
    chapter: 'Chapitre',
    lesson: 'Lecon',
    explanation: 'Explication',
    example: 'Exemple',
    exercise: 'Exercice',
    chatbot_context: 'Chatbot',
    revision: 'Revision',
  }
  return labels[type] || type
}

export default RemediationPage
