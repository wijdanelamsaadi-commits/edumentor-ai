import { useEffect, useMemo, useState } from 'react'
import { BarChart3, BookOpen, Calendar, CheckCircle2, Star } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useLearning } from '../hooks/useLearning.js'

const recommendationsByLevel = {
  debutant: [
    {
      icon: BookOpen,
      title: "Introduction à l’IA",
      subtitle: 'Revoir les bases avant de continuer',
      action: 'Continuer',
      path: '/courses/1',
    },
    {
      icon: Star,
      title: 'Test diagnostique',
      subtitle: 'Renforcer les notions fondamentales',
      action: 'Revoir',
      path: '/diagnostic',
    },
  ],
  intermediaire: [
    {
      icon: BookOpen,
      title: 'Machine Learning',
      subtitle: 'Chapitre 2 : Algorithmes supervisés',
      action: 'Continuer',
      path: '/courses/2',
    },
    {
      icon: Star,
      title: 'Quiz - Prompt Engineering',
      subtitle: 'Consolider votre progression',
      action: 'Commencer',
      path: '/quiz/1',
    },
  ],
  avance: [
    {
      icon: BookOpen,
      title: 'RAG (Retrieval-Augmented Generation)',
      subtitle: 'Passer aux concepts avancés',
      action: 'Commencer',
      path: '/courses/4',
    },
    {
      icon: Star,
      title: 'Responsible AI',
      subtitle: 'Approfondir les enjeux éthiques',
      action: 'Explorer',
      path: '/courses/5',
    },
  ],
}

function DashboardPage() {
  const navigate = useNavigate()
  const { diagnosticLevel, learner, quizScore } = useLearning()
  const [diagnosticResult, setDiagnosticResult] = useState(null)

  useEffect(() => {
    try {
      const storedResult = localStorage.getItem('diagnosticResult')
      setDiagnosticResult(storedResult ? JSON.parse(storedResult) : null)
    } catch {
      setDiagnosticResult(null)
    }
  }, [])

  const normalizedLevel = normalizeLevel(diagnosticResult?.level || diagnosticLevel)
  const displayLevel = diagnosticResult?.level || 'Test diagnostique non encore passé'
  const displayScore = Number.isFinite(diagnosticResult?.score) ? `${diagnosticResult.score}%` : '--'
  const displayDate = diagnosticResult?.date ? formatDiagnosticDate(diagnosticResult.date) : 'Aucun test'
  const visualProgress = Number.isFinite(diagnosticResult?.score) ? diagnosticResult.score : 0
  const recommendations = useMemo(() => {
    if (!diagnosticResult) {
      return [
        {
          icon: BarChart3,
          title: 'Test diagnostique non encore passé',
          subtitle: 'Passez le test pour personnaliser votre parcours',
          action: 'Passer le test',
          path: '/diagnostic',
        },
      ]
    }

    return recommendationsByLevel[normalizedLevel] || recommendationsByLevel.intermediaire
  }, [diagnosticResult, normalizedLevel])

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Bonjour, {learner.name} 👋</h1>
        <p>Prête à continuer votre apprentissage aujourd'hui ?</p>
      </div>

      <div className="dashboard-stats">
        <article className="metric-card metric-wide">
          <span className="soft-icon"><BarChart3 size={42} /></span>
          <div>
            <p>Niveau actuel</p>
            <h2>{displayLevel}</h2>
            {diagnosticResult ? (
              <strong>Niveau obtenu au dernier test</strong>
            ) : (
              <button className="outline-button" onClick={() => navigate('/diagnostic')} type="button">Passer le test</button>
            )}
          </div>
        </article>
        <article className="metric-card">
          <p>Score diagnostique</p>
          <h2>{displayScore}</h2>
          <div className="progress-track"><span style={{ width: `${visualProgress}%` }} /></div>
          <strong>{diagnosticResult ? 'Score réel obtenu' : 'En attente du test'}</strong>
        </article>
        <article className="metric-card">
          <span className="soft-icon"><Calendar size={42} /></span>
          <p>Dernier test</p>
          <h2>{displayDate}</h2>
          <strong>{diagnosticResult ? 'Résultat sauvegardé' : 'Test diagnostique non encore passé'}</strong>
        </article>
      </div>

      <div className="dashboard-grid">
        <article className="panel-card history-panel">
          <div className="panel-title">
            <h2>Historique</h2>
            <button type="button">Voir tout →</button>
          </div>
          {[
            ['Quiz terminé : Introduction à l’IA', `Score obtenu : ${quizScore || 80}%`, "Aujourd'hui", '10:35', CheckCircle2],
            ['Cours poursuivi : Machine Learning', 'Chapitre 2 : Algorithmes supervisés', "Aujourd'hui", '09:10', BookOpen],
            ['Quiz terminé : Machine Learning', 'Score obtenu : 70%', 'Hier', '18:42', CheckCircle2],
            [
              diagnosticResult ? 'Test diagnostique complété' : 'Test diagnostique non encore passé',
              diagnosticResult ? `Niveau obtenu : ${diagnosticResult.level} - Score : ${diagnosticResult.score}%` : 'Passez le test pour personnaliser votre parcours',
              diagnosticResult ? displayDate : 'À faire',
              diagnosticResult ? '' : '',
              BarChart3,
            ],
          ].map(([title, text, day, time, Icon]) => (
            <div className="history-item" key={title}>
              <span><Icon size={22} /></span>
              <div>
                <strong>{title}</strong>
                <p>{text}</p>
              </div>
              <time>{day}<br />{time}</time>
            </div>
          ))}
        </article>

        <article className="panel-card recommend-panel">
          <div className="panel-title">
            <h2>Recommandé pour vous</h2>
            <button type="button">Voir tout</button>
          </div>
          {recommendations.map((item) => (
            <RecommendedItem
              action={item.action}
              icon={item.icon}
              key={item.title}
              onClick={() => navigate(item.path)}
              subtitle={item.subtitle}
              title={item.title}
            />
          ))}
        </article>
      </div>

      <article className="continue-card">
        <span><BookOpen size={44} /></span>
        <div>
          <h2>Continuer le dernier chapitre</h2>
          <h3>Prompt Engineering</h3>
          <p>Chapitre 3 : Techniques avancées</p>
          <div className="inline-progress">
            <div className="progress-track"><span style={{ width: '65%' }} /></div>
            <strong>65%</strong>
          </div>
        </div>
        <button className="primary-button" onClick={() => navigate('/courses/3')}>Continuer</button>
      </article>
    </section>
  )
}

function normalizeLevel(level) {
  const normalized = String(level || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')

  if (normalized.includes('debut') || normalized.includes('dã')) return 'debutant'
  if (normalized.includes('avance') || normalized.includes('avanc')) return 'avance'
  return 'intermediaire'
}

function formatDiagnosticDate(dateValue) {
  const date = new Date(dateValue)

  if (Number.isNaN(date.getTime())) {
    return 'Date inconnue'
  }

  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date)
}

function RecommendedItem({ icon: Icon, title, subtitle, action, onClick }) {
  return (
    <div className="recommended-item">
      <span className="soft-icon"><Icon size={34} /></span>
      <div>
        <strong>{title}</strong>
        <p>{subtitle}</p>
      </div>
      <button className="outline-button" onClick={onClick}>{action}</button>
    </div>
  )
}

export default DashboardPage
