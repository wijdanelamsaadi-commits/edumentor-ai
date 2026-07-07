import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, BookOpen, CheckCircle2, Download, FileText, Lock, Play, Target } from 'lucide-react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { useLearning } from '../hooks/useLearning.js'

function CourseDetailPage() {
  const navigate = useNavigate()
  const { id } = useParams()
  const { courses } = useLearning()
  const course = courses.find((item) => item.id === Number(id))
  const [diagnosticResult, setDiagnosticResult] = useState(null)

  useEffect(() => {
    try {
      const storedResult = localStorage.getItem('diagnosticResult')
      setDiagnosticResult(storedResult ? JSON.parse(storedResult) : null)
    } catch {
      setDiagnosticResult(null)
    }
  }, [])

  const learnerLevel = getDisplayLevel(diagnosticResult?.level || course?.level)
  const normalizedLevel = normalizeLevel(learnerLevel)
  const pedagogicalContent = useMemo(
    () => getPedagogicalContent(course, normalizedLevel),
    [course, normalizedLevel],
  )

  if (!course) {
    return <Navigate to="/courses" replace />
  }

  return (
    <section className="page-section course-detail-page">
      <button className="back-link" onClick={() => navigate('/courses')} type="button"><ArrowLeft size={20} /> Retour aux cours</button>
      <div className="detail-layout">
        <div className="detail-main">
          <section className="course-hero">
            <span className="course-big-icon"><BookOpen size={64} /><strong>{course.tag}</strong></span>
            <div>
              <h1>{course.title}</h1>
              <span className="course-level-badge">Adapté à votre niveau : {learnerLevel}</span>
              <p>{pedagogicalContent.intro}</p>
              <div className="course-hero-progress">
                <span>Progression dans ce cours</span>
                <div className="progress-track"><span style={{ width: `${course.progress}%` }} /></div>
                <strong>{course.progress}%</strong>
                <small>(3/4 chapitres)</small>
              </div>
            </div>
          </section>

          <nav className="tabs-row">
            <button className="active" type="button"><BookOpen size={18} />Contenu</button>
            <button type="button"><FileText size={18} />Résumé</button>
            <button type="button"><CheckCircle2 size={18} />Exemples</button>
            <button type="button"><Target size={18} />Objectifs</button>
          </nav>

          <ContentPanel pedagogicalContent={pedagogicalContent} />
        </div>
        <aside className="detail-side">
          <article className="panel-card course-info">
            <h2>Informations du cours</h2>
            <InfoLine label="Niveau" value={learnerLevel} highlight />
            <InfoLine label="Durée estimée" value={pedagogicalContent.duration} />
            <InfoLine label="Chapitres" value="4" />
            <InfoLine label="Langue" value="Français" />
            <InfoLine label="Dernière mise à jour" value="12/05/2024" />
          </article>
          <article className="panel-card center-card">
            <button className="primary-button quiz-cta" onClick={() => navigate(`/quiz/${course.id}`)} type="button"><FileText size={24} />Commencer le quiz</button>
            <p>Testez vos connaissances sur ce cours</p>
          </article>
          <button className="download-button" type="button"><Download size={22} />Télécharger le support PDF</button>
          <article className="quote-card">“<p>L'IA ne remplacera pas les humains. Mais les humains qui utilisent l'IA remplaceront ceux qui ne le font pas.</p><span>— Andrew Ng</span></article>
        </aside>
      </div>
    </section>
  )
}

function ContentPanel({ pedagogicalContent }) {
  return (
    <>
      <article className="panel-card content-panel">
        <h2>Contenu</h2>
        {pedagogicalContent.lessons.map((item, index) => (
          <div className={index === 2 ? 'lesson-row active' : 'lesson-row'} key={item}>
            <span>{index < 3 ? <Play size={18} /> : <Lock size={18} />}</span>
            <strong>{index + 1}. {item}</strong>
            <time>{[15, 18, 20, 17][index] || 15} min</time>
            {index < 2 && <CheckCircle2 size={22} />}
          </div>
        ))}
      </article>
      <article className="panel-card lesson-panel">
        <h2>Résumé</h2>
        <p>{pedagogicalContent.summary}</p>
      </article>
      <article className="panel-card examples-panel">
        <h2>Exemples</h2>
        <div className="example-grid">
          {pedagogicalContent.examples.map((item) => <div key={item.title}><span /> <strong>{item.title}</strong><p>{item.description}</p></div>)}
        </div>
      </article>
      <article className="panel-card objectives-panel">
        <h2>Objectifs</h2>
        {pedagogicalContent.objectives.map((item) => <p key={item}><Target size={20} />{item}</p>)}
      </article>
      <article className="panel-card objectives-panel">
        <h2>Compétences acquises</h2>
        {pedagogicalContent.skills.map((item) => <p key={item}><CheckCircle2 size={20} />{item}</p>)}
      </article>
    </>
  )
}

function InfoLine({ label, value, highlight }) {
  return <p><span>{label}</span><strong className={highlight ? 'red-text' : ''}>{value}</strong></p>
}

function normalizeLevel(level) {
  const normalized = String(level || '')
    .replace(/\u00c3\u00a9/g, 'e')
    .replace(/\u00c3\u00a8/g, 'e')
    .replace(/\u00c3\u00a0/g, 'a')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')

  if (normalized.includes('debut')) return 'debutant'
  if (normalized.includes('avance') || normalized.includes('avanc')) return 'avance'
  return normalized.includes('inter') ? 'intermediaire' : 'debutant'
}

function getDisplayLevel(level) {
  const normalizedLevel = normalizeLevel(level)
  if (normalizedLevel === 'avance') return 'Avancé'
  if (normalizedLevel === 'intermediaire') return 'Intermédiaire'
  return 'Débutant'
}

function getPedagogicalContent(course, normalizedLevel) {
  const title = course?.title || 'ce cours'
  const baseObjectives = course?.objectives || []
  const baseExamples = course?.examples || []

  const contentByLevel = {
    debutant: {
      duration: course?.duration || '1h 20m',
      intro: `Ce module présente ${title} avec des mots simples, des repères progressifs et des exemples faciles à relier à la vie quotidienne.`,
      summary: `À ce niveau, l'objectif est de comprendre l'idée générale de ${title}, de reconnaître les notions importantes et de savoir expliquer le concept avec vos propres mots avant de passer aux exercices.`,
      lessons: [
        `Comprendre le rôle de ${title}`,
        'Identifier les mots-clés essentiels',
        'Observer un exemple guidé pas à pas',
        'Répondre à des questions simples de validation',
      ],
      examples: baseExamples.map((item) => ({
        title: item,
        description: 'Exemple simple pour visualiser la notion sans détail technique inutile.',
      })),
      objectives: [
        ...baseObjectives.slice(0, 3),
        'Reformuler le cours avec un vocabulaire clair.',
        'Reconnaître une situation où cette notion peut être utilisée.',
      ],
      skills: [
        'Expliquer la notion principale simplement.',
        'Repérer les concepts de base dans un cas concret.',
        'Préparer le quiz avec des repères clairs.',
      ],
    },
    intermediaire: {
      duration: course?.duration || '1h 45m',
      intro: `Ce module approfondit ${title} avec une explication structurée, des liens entre concepts et des exercices pour consolider la compréhension.`,
      summary: `À ce niveau, vous reliez ${title} à des cas d'usage concrets, vous comparez les approches possibles et vous commencez à justifier vos choix avec un vocabulaire plus précis.`,
      lessons: [
        `Situer ${title} dans un projet IA`,
        'Comprendre les mécanismes importants',
        "Analyser un cas d'usage guidé",
        "S'entraîner avec un exercice corrigé",
      ],
      examples: baseExamples.map((item) => ({
        title: item,
        description: 'Cas concret pour analyser les étapes, les limites et les choix à effectuer.',
      })),
      objectives: [
        ...baseObjectives,
        'Comparer plusieurs usages possibles.',
        'Justifier une réponse avec les notions du cours.',
      ],
      skills: [
        'Analyser une situation pédagogique ou métier.',
        'Choisir les notions utiles selon le contexte.',
        "Résoudre un exercice d'application intermédiaire.",
      ],
    },
    avance: {
      duration: course?.duration || '2h',
      intro: `Ce module traite ${title} de manière approfondie avec une vision projet, des limites méthodologiques et des critères d'évaluation.`,
      summary: `À ce niveau, vous utilisez ${title} pour raisonner sur des scénarios plus complexes, anticiper les risques, évaluer les compromis et produire une réponse argumentée.`,
      lessons: [
        `Modéliser un scénario avancé autour de ${title}`,
        'Évaluer les choix techniques ou pédagogiques',
        'Identifier limites, risques et biais',
        'Construire une recommandation argumentée',
      ],
      examples: baseExamples.map((item) => ({
        title: item,
        description: 'Situation avancée pour discuter performance, fiabilité, limites et amélioration.',
      })),
      objectives: [
        ...baseObjectives,
        "Évaluer la pertinence d'une solution dans un contexte réel.",
        'Formuler une recommandation claire et argumentée.',
      ],
      skills: [
        'Évaluer une approche avec des critères précis.',
        "Identifier les limites et les risques d'un usage IA.",
        'Produire une synthèse ou une recommandation avancée.',
      ],
    },
  }

  return contentByLevel[normalizedLevel] || contentByLevel.debutant
}

export default CourseDetailPage
