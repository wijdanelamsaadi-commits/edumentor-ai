import { useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, CheckCircle2, ClipboardList, XCircle } from 'lucide-react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { useLearning } from '../hooks/useLearning.js'

function QuizPage() {
  const navigate = useNavigate()
  const { id } = useParams()
  const { courses, quizResults, saveQuizResult } = useLearning()
  const course = courses.find((item) => item.id === Number(id))
  const [currentIndex, setCurrentIndex] = useState(0)
  const [answers, setAnswers] = useState({})
  const [isFinished, setIsFinished] = useState(false)

  const questions = useMemo(() => buildCourseQuiz(course), [course])
  const currentQuestion = questions[currentIndex]
  const progress = Math.round(((currentIndex + 1) / questions.length) * 100)
  const answeredCount = Object.keys(answers).length
  const result = useMemo(() => calculateResult(questions, answers), [answers, questions])
  const savedResult = course ? quizResults[course.id] : null
  const visibleScore = isFinished ? result.score : savedResult?.score

  if (!course) {
    return <Navigate to="/courses" replace />
  }

  function selectAnswer(choice) {
    if (isFinished) return
    setAnswers((current) => ({ ...current, [currentIndex]: choice }))
  }

  function goToPrevious() {
    setCurrentIndex((index) => Math.max(index - 1, 0))
  }

  function goToNext() {
    if (isFinished) {
      setCurrentIndex((index) => Math.min(index + 1, questions.length - 1))
      return
    }

    if (currentIndex < questions.length - 1) {
      setCurrentIndex((index) => index + 1)
      return
    }

    finishQuiz()
  }

  function finishQuiz() {
    const finalResult = calculateResult(questions, answers)
    setIsFinished(true)
    saveQuizResult(course.id, {
      score: finalResult.score,
      correct: finalResult.correct,
      total: questions.length,
      answers,
      questions: questions.map(({ question, answer, explanation }) => ({ question, answer, explanation })),
    })
  }

  return (
    <section className="page-section quiz-page">
      <button className="back-link" onClick={() => navigate(`/courses/${course.id}`)} type="button"><ArrowLeft size={20} /> Retour au cours</button>
      <div className="quiz-header">
        <span className="soft-icon"><ClipboardList size={44} /></span>
        <div>
          <h1>Quiz - {course.title}</h1>
          <p>Testez vos connaissances sur ce chapitre.</p>
        </div>
      </div>
      <div className="test-progress">
        <span>Question <strong>{currentIndex + 1}</strong> sur {questions.length}</span>
        <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
        <strong>{progress}%</strong>
      </div>

      <div className="quiz-layout">
        <div>
          <article className="question-card quiz-card">
            <h2>Question {currentIndex + 1}</h2>
            <h3>{currentQuestion.question}</h3>
            <div className="answer-list">
              {currentQuestion.choices.map((choice, index) => {
                const isSelected = answers[currentIndex] === choice
                const isCorrect = isFinished && choice === currentQuestion.answer
                const isWrong = isFinished && isSelected && choice !== currentQuestion.answer

                return (
                  <button
                    className={getAnswerClassName(isSelected, isCorrect, isWrong)}
                    key={choice}
                    onClick={() => selectAnswer(choice)}
                    type="button"
                  >
                    <span />{String.fromCharCode(65 + index)}. {choice}
                    {(isSelected || isCorrect) && <CheckCircle2 size={20} />}
                  </button>
                )
              })}
            </div>
            <div className="question-actions">
              <button className="ghost-button" disabled={currentIndex === 0} onClick={goToPrevious} type="button"><ArrowLeft size={20} />Précédent</button>
              <button className="primary-button" disabled={!answers[currentIndex]} onClick={goToNext} type="button">
                {!isFinished && currentIndex === questions.length - 1 ? 'Terminer' : 'Suivant'} <ArrowRight size={20} />
              </button>
            </div>
          </article>

          {isFinished && (
            <>
              <article className="panel-card correction-card">
                <h2>Correction</h2>
                <strong><CheckCircle2 size={22} />{answers[currentIndex] === currentQuestion.answer ? 'Bonne réponse !' : 'Correction'}</strong>
                <p>La réponse correcte est : {currentQuestion.answer}</p>
              </article>
              <article className="panel-card explanation-card">
                <h2>Explication</h2>
                <p>{currentQuestion.explanation}</p>
                <div className="success-note"><strong>Score final</strong><p>{result.correct} bonnes réponses sur {questions.length}, soit {result.score}%.</p></div>
                <div className="danger-note"><strong>À revoir :</strong><p>{result.score >= 70 ? 'Continuez avec les exercices avancés du cours.' : 'Relisez le résumé du cours avant de refaire le quiz.'}</p></div>
              </article>
            </>
          )}
        </div>
        <aside className="quiz-side">
          <article className="panel-card score-card">
            <h2>Votre score</h2>
            <div className="score-ring"><strong>{visibleScore ?? 0}%</strong><span>{isFinished ? result.correct : savedResult?.correct || 0} / {questions.length}</span></div>
            <p><CheckCircle2 size={18} />Bonnes réponses <strong>{isFinished ? result.correct : savedResult?.correct || 0}</strong></p>
            <p><XCircle size={18} />Mauvaises réponses <strong>{isFinished ? questions.length - result.correct : savedResult ? questions.length - savedResult.correct : 0}</strong></p>
          </article>
          <article className="panel-card question-index">
            <h2>Questions</h2>
            {questions.map((question, index) => (
              <p key={question.question} className={index === currentIndex ? 'active' : ''}>
                <span>{index + 1}</span>{getQuestionStatus(index, answers, questions, isFinished)}
              </p>
            ))}
            <button className="primary-button" disabled={answeredCount < questions.length || isFinished} onClick={finishQuiz} type="button">Voir le résumé</button>
          </article>
        </aside>
      </div>
    </section>
  )
}

function getAnswerClassName(isSelected, isCorrect, isWrong) {
  if (isCorrect) return 'answer-option selected correct'
  if (isWrong) return 'answer-option selected'
  if (isSelected) return 'answer-option selected'
  return 'answer-option'
}

function getQuestionStatus(index, answers, questions, isFinished) {
  if (!answers[index]) return 'Non répondu'
  if (!isFinished) return 'Répondu'
  return answers[index] === questions[index].answer ? 'Correct' : 'Incorrect'
}

function calculateResult(questions, answers) {
  const correct = questions.filter((question, index) => answers[index] === question.answer).length
  return {
    correct,
    score: Math.round((correct / questions.length) * 100),
  }
}

function buildCourseQuiz(course) {
  if (!course) return []

  const title = course.title
  const examples = course.examples?.length ? course.examples : ['un cas concret', 'un exercice guidé', 'une mise en situation']
  const objectives = course.objectives?.length ? course.objectives : ['Comprendre le concept', 'Appliquer la notion', 'Évaluer une réponse']

  return [
    {
      question: `Quel est l'objectif principal du cours "${title}" ?`,
      choices: [course.summary, 'Modifier les couleurs de l’interface', 'Créer un mot de passe utilisateur'],
      answer: course.summary,
      explanation: `Le quiz vérifie d'abord que vous avez compris le but pédagogique du cours : ${course.summary}`,
    },
    {
      question: `Quelle compétence est directement liée à "${title}" ?`,
      choices: [objectives[0], 'Installer un navigateur web', 'Changer la langue du clavier'],
      answer: objectives[0],
      explanation: 'Une compétence attendue doit correspondre aux objectifs pédagogiques du cours.',
    },
    {
      question: `Quel exemple illustre le mieux ce cours ?`,
      choices: [examples[0], 'Une image décorative', 'Un bouton sans action'],
      answer: examples[0],
      explanation: `L'exemple "${examples[0]}" permet de relier la notion du cours à une situation concrète.`,
    },
    {
      question: 'Pourquoi faut-il consulter les exemples pendant le cours ?',
      choices: ['Pour transformer une notion abstraite en cas concret', 'Pour ignorer les objectifs', 'Pour éviter toute évaluation'],
      answer: 'Pour transformer une notion abstraite en cas concret',
      explanation: 'Les exemples aident à appliquer la théorie dans un contexte compréhensible.',
    },
    {
      question: 'Quelle attitude permet de mieux progresser après une mauvaise réponse ?',
      choices: ['Lire la correction et refaire un exercice ciblé', 'Fermer le cours immédiatement', 'Supprimer son score'],
      answer: 'Lire la correction et refaire un exercice ciblé',
      explanation: 'La correction explique l’erreur et donne une piste de révision utile.',
    },
    {
      question: `Dans "${title}", que faut-il savoir faire avant le quiz ?`,
      choices: [objectives[1] || objectives[0], 'Changer le logo de la plateforme', 'Créer un compte administrateur'],
      answer: objectives[1] || objectives[0],
      explanation: 'Le quiz est lié aux objectifs vus dans le cours, pas aux éléments techniques de la plateforme.',
    },
    {
      question: 'Quel indicateur montre que l’apprentissage avance ?',
      choices: ['La progression et le score du quiz', 'La taille de l’écran', 'Le nombre de couleurs utilisées'],
      answer: 'La progression et le score du quiz',
      explanation: 'EduMentor AI suit les scores et la progression pour recommander les prochaines étapes.',
    },
    {
      question: `Quelle deuxième illustration peut accompagner "${title}" ?`,
      choices: [examples[1] || examples[0], 'Un champ vide', 'Une page sans contenu'],
      answer: examples[1] || examples[0],
      explanation: 'Les exemples du cours sont choisis pour renforcer la compréhension du thème.',
    },
    {
      question: 'Que doit contenir une bonne réponse pédagogique ?',
      choices: ['Une idée claire, un exemple et une justification', 'Uniquement un mot isolé', 'Une réponse sans rapport avec le cours'],
      answer: 'Une idée claire, un exemple et une justification',
      explanation: 'Une réponse utile explique la notion et montre comment l’appliquer.',
    },
    {
      question: `Après le quiz "${title}", quelle action est la plus pertinente ?`,
      choices: ['Consulter la correction puis continuer la progression', 'Ignorer le résultat obtenu', 'Revenir à la page login sans raison'],
      answer: 'Consulter la correction puis continuer la progression',
      explanation: 'Le score sauvegardé sert à suivre la progression et à orienter les révisions.',
    },
  ]
}

export default QuizPage
