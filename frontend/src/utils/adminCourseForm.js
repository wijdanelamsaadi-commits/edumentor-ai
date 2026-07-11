export function updateCourseDraftFactory(setCourseDraft) {
  return (field, value) => setCourseDraft((current) => ({ ...current, [field]: value }))
}

export function createEmptyCourseDraft() {
  return {
    title: '',
    level: 'Debutant',
    duration: '2h',
    display_order: 99,
    summary: '',
    description: '',
    objectivesText: '',
    chaptersText: 'Introduction | 20 min | active',
    examplesText: '',
    skillsText: '',
    quizText: createDefaultQuizText(),
    published: true,
  }
}

export function courseToDraft(course) {
  return {
    title: course.title || '',
    level: course.level || 'Debutant',
    duration: course.duration || '2h',
    display_order: course.display_order || course.id,
    summary: course.summary || '',
    description: course.description || '',
    objectivesText: (course.objectives || []).join('\n'),
    chaptersText: (course.chapters || []).map((chapter) => `${chapter.title} | ${chapter.duration || '20 min'} | ${chapter.status || 'locked'}`).join('\n'),
    examplesText: (course.examples || []).map((example) => `${example.title} | ${example.description || ''}`).join('\n'),
    skillsText: (course.skills || []).join('\n'),
    quizText: ((course.quiz?.questions || []).length >= 10 ? course.quiz.questions : []).map((question) => (
      `${question.question} | ${(question.choices || []).join(';')} | ${question.answer || question.choices?.[0] || ''} | ${question.explanation || ''}`
    )).join('\n') || createDefaultQuizText(),
    published: course.published !== false,
  }
}

export function draftToCoursePayload(draft) {
  const chapters = parseLines(draft.chaptersText).map((line, index) => {
    const [title, duration = '20 min', status = index === 0 ? 'active' : 'locked'] = line.split('|').map((part) => part.trim())
    return {
      title,
      duration,
      status,
      completed: status === 'completed',
      openable: ['completed', 'active'].includes(status),
    }
  })
  const quizQuestions = parseQuiz(draft.quizText)

  return {
    title: draft.title,
    level: draft.level,
    duration: draft.duration,
    display_order: Number(draft.display_order || 99),
    summary: draft.summary,
    description: draft.description,
    objectives: parseLines(draft.objectivesText),
    chapters,
    examples: parseLines(draft.examplesText).map((line) => {
      const [title, description = ''] = line.split('|').map((part) => part.trim())
      return { title, description }
    }),
    skills: parseLines(draft.skillsText),
    information: {
      level: draft.level,
      duration: draft.duration,
      language: 'Francais',
      last_update: new Date().toLocaleDateString('fr-FR'),
      chapter_count: chapters.length,
    },
    published: draft.published,
    quiz: {
      title: `Quiz - ${draft.title || 'Cours'}`,
      published: true,
      questions: quizQuestions,
    },
  }
}

function parseLines(value) {
  return String(value || '').split('\n').map((line) => line.trim()).filter(Boolean)
}

function parseQuiz(value) {
  const questions = parseLines(value).map((line) => {
    const [question, choicesText, answer, explanation = ''] = line.split('|').map((part) => part.trim())
    const choices = String(choicesText || '').split(';').map((choice) => choice.trim()).filter(Boolean)
    return { question, choices, answer: answer || choices[0] || '', explanation }
  }).filter((item) => item.question && item.choices.length >= 2 && item.answer)

  if (questions.length < 10) {
    throw new Error('Le quiz doit contenir au moins 10 questions valides.')
  }

  return questions
}

function createDefaultQuizText() {
  return Array.from({ length: 10 }, (_, index) => {
    const number = index + 1
    return `Question ${number} ? | Bonne reponse ${number};Option B ${number};Option C ${number} | Bonne reponse ${number} | Explication de la question ${number}.`
  }).join('\n')
}
