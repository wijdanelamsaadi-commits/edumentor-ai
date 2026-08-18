import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  createProfessorQuiz,
  createProfessorQuizQuestion,
  deleteProfessorQuizQuestion,
  fetchDifficultyLevels,
  getProfessorCourse,
  getProfessorQuizzes,
  updateProfessorQuiz,
  updateProfessorQuizQuestion,
} from '../services/api.js'

function ProfessorQuizPage() {
  const { id } = useParams()
  const [course, setCourse] = useState(null)
  const [quiz, setQuiz] = useState(null)
  const [difficulties, setDifficulties] = useState([])
  const [quizDraft, setQuizDraft] = useState({ title: 'Quiz du cours', description: '', passing_score: 70, active: true, published: true })
  const [questionDraft, setQuestionDraft] = useState({ question: '', choices: 'Oui\nNon', answer: '', explanation: '', chapter_id: '', difficulty_level_id: '' })
  const [message, setMessage] = useState('')

  useEffect(() => {
    Promise.all([getProfessorCourse(id), getProfessorQuizzes(id), fetchDifficultyLevels()])
      .then(([courseData, quizzesData, difficultyData]) => {
        setCourse(courseData)
        setDifficulties(difficultyData)
        const firstQuiz = quizzesData[0]
        if (firstQuiz) {
          setQuiz(firstQuiz)
          setQuizDraft({
            title: firstQuiz.title || 'Quiz du cours',
            description: firstQuiz.description || '',
            passing_score: firstQuiz.passing_score || 70,
            active: firstQuiz.active !== false,
            published: firstQuiz.published !== false,
          })
        }
      })
      .catch((err) => setMessage(err.message || 'Impossible de charger le quiz.'))
  }, [id])

  const studentPreview = useMemo(() => quiz?.questions?.slice(0, 3) || [], [quiz])

  async function saveQuiz() {
    try {
      const saved = quiz ? await updateProfessorQuiz(quiz.id, quizDraft) : await createProfessorQuiz(id, quizDraft)
      setQuiz(saved)
      setMessage('Quiz sauvegardé.')
    } catch (err) {
      setMessage(err.message || 'Sauvegarde quiz impossible.')
    }
  }

  async function addQuestion() {
    if (!quiz) {
      setMessage('Créez le quiz avant d’ajouter des questions.')
      return
    }
    try {
      const choices = questionDraft.choices.split('\n').map((choice) => choice.trim()).filter(Boolean)
      await createProfessorQuizQuestion(quiz.id, {
        question: questionDraft.question,
        choices,
        answer: questionDraft.answer || choices[0],
        explanation: questionDraft.explanation,
        chapter_id: Number(questionDraft.chapter_id) || null,
        difficulty_level_id: Number(questionDraft.difficulty_level_id) || null,
      })
      const refreshed = await getProfessorQuizzes(id)
      setQuiz(refreshed[0])
      setQuestionDraft({ question: '', choices: 'Oui\nNon', answer: '', explanation: '', chapter_id: '', difficulty_level_id: '' })
      setMessage('Question ajoutée.')
    } catch (err) {
      setMessage(err.message || 'Ajout question impossible.')
    }
  }

  async function updateQuestion(question, changes) {
    try {
      await updateProfessorQuizQuestion(quiz.id, question.id, { ...question, ...changes })
      const refreshed = await getProfessorQuizzes(id)
      setQuiz(refreshed[0])
    } catch (err) {
      setMessage(err.message || 'Modification question impossible.')
    }
  }

  async function removeQuestion(questionId) {
    if (!window.confirm('Supprimer cette question ?')) return
    try {
      await deleteProfessorQuizQuestion(quiz.id, questionId)
      const refreshed = await getProfessorQuizzes(id)
      setQuiz(refreshed[0])
    } catch (err) {
      setMessage(err.message || 'Suppression question impossible.')
    }
  }

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Quiz du cours</h1>
          <p>{course?.title || 'Gestion du quiz et des questions.'}</p>
        </div>
        <Link className="outline-button" to="/professor/courses">Retour aux cours</Link>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <article className="panel-card admin-course-form">
        <h3>Paramètres du quiz</h3>
        <label>Titre<input onChange={(event) => setQuizDraft((prev) => ({ ...prev, title: event.target.value }))} value={quizDraft.title} /></label>
        <label>Description<textarea onChange={(event) => setQuizDraft((prev) => ({ ...prev, description: event.target.value }))} value={quizDraft.description} /></label>
        <div className="admin-form-row">
          <label>Score de réussite<input min="0" max="100" onChange={(event) => setQuizDraft((prev) => ({ ...prev, passing_score: Number(event.target.value) }))} type="number" value={quizDraft.passing_score} /></label>
          <label>Actif<select onChange={(event) => setQuizDraft((prev) => ({ ...prev, active: event.target.value === 'true', published: event.target.value === 'true' }))} value={String(quizDraft.active)}>
            <option value="true">Oui</option>
            <option value="false">Non</option>
          </select></label>
          <button className="primary-button" onClick={saveQuiz} type="button">{quiz ? 'Sauvegarder' : 'Créer le quiz'}</button>
        </div>
      </article>

      <article className="panel-card admin-course-form">
        <h3>Questions</h3>
        {(quiz?.questions || []).map((question) => (
          <div className="professor-question-editor" key={question.id}>
            <input onChange={(event) => updateQuestion(question, { question: event.target.value })} value={question.question} />
            <select onChange={(event) => updateQuestion(question, { answer: event.target.value })} value={question.answer}>
              {(question.choices || []).map((choice) => <option key={choice} value={choice}>{choice}</option>)}
            </select>
            <select onChange={(event) => updateQuestion(question, { active: event.target.value === 'true' })} value={String(question.active)}>
              <option value="true">Active</option>
              <option value="false">Inactive</option>
            </select>
            <button onClick={() => removeQuestion(question.id)} type="button">Supprimer</button>
          </div>
        ))}
        <label>Nouvelle question<input onChange={(event) => setQuestionDraft((prev) => ({ ...prev, question: event.target.value }))} value={questionDraft.question} /></label>
        <label>Choix (un par ligne)<textarea onChange={(event) => setQuestionDraft((prev) => ({ ...prev, choices: event.target.value }))} value={questionDraft.choices} /></label>
        <label>Réponse correcte<input onChange={(event) => setQuestionDraft((prev) => ({ ...prev, answer: event.target.value }))} placeholder="Doit correspondre à un choix" value={questionDraft.answer} /></label>
        <label>Explication<textarea onChange={(event) => setQuestionDraft((prev) => ({ ...prev, explanation: event.target.value }))} value={questionDraft.explanation} /></label>
        <div className="admin-form-row">
          <label>Chapitre<select onChange={(event) => setQuestionDraft((prev) => ({ ...prev, chapter_id: event.target.value }))} value={questionDraft.chapter_id}>
            <option value="">Aucun</option>
            {(course?.chapters || []).map((chapter) => <option key={chapter.id} value={chapter.id}>{chapter.title}</option>)}
          </select></label>
          <label>Difficulté<select onChange={(event) => setQuestionDraft((prev) => ({ ...prev, difficulty_level_id: event.target.value }))} value={questionDraft.difficulty_level_id}>
            <option value="">Aucune</option>
            {difficulties.map((difficulty) => <option key={difficulty.id} value={difficulty.id}>{difficulty.name}</option>)}
          </select></label>
          <button className="primary-button" onClick={addQuestion} type="button">Ajouter la question</button>
        </div>
      </article>

      <article className="panel-card">
        <div className="panel-title">
          <h2>Aperçu étudiant</h2>
          <p>{quiz?.questions?.length || 0} questions</p>
        </div>
        {studentPreview.length ? studentPreview.map((question) => (
          <div className="question-index" key={`preview-${question.id}`}>
            <p><span>{question.position}</span>{question.question}</p>
          </div>
        )) : <p className="admin-empty">Aucune question à prévisualiser.</p>}
      </article>
    </section>
  )
}

export default ProfessorQuizPage
