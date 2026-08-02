import {
  Brain,
  Clipboard,
  Download,
  FileText,
  Plus,
  RefreshCcw,
  Search,
  Send,
  Sparkles,
  Square,
  ThumbsDown,
  ThumbsUp,
  Trash2,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { API_BASE_URL, fetchCourseRagStatus, fetchCourses, fetchSubjects, sendChatMessage } from '../services/api.js'
import { addNotification } from '../services/notifications.js'

const CHAT_SESSIONS_KEY = 'edumentor:chatSessions'
const CHAT_XP_KEY = 'edumentor:chatXP'
const CHAT_FEEDBACK_KEY = 'edumentor:chatFeedback'
const PREFERENCES_STORAGE_KEY = 'edumentor:preferences'
const STREAM_CHUNK_SIZE = 12
const STREAM_DELAY_MS = 20
const DEFAULT_CHAT_PREFERENCES = {
  chatbotMiniQuiz: true,
  questionSuggestions: true,
  simulatedStreaming: true,
}

function ChatbotPage() {
  const streamTimerRef = useRef(null)
  const stopStreamingRef = useRef(false)
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [diagnosticResult, setDiagnosticResult] = useState(null)
  const [sessions, setSessions] = useState(() => readSessions())
  const [activeSessionId, setActiveSessionId] = useState(() => readSessions()[0]?.id || createSession().id)
  const [historySearch, setHistorySearch] = useState('')
  const [quizAnswers, setQuizAnswers] = useState({})
  const [feedback, setFeedback] = useState(() => readLocalStorage(CHAT_FEEDBACK_KEY, {}))
  const [xp, setXp] = useState(() => Number(readLocalStorage(CHAT_XP_KEY, 0)))
  const [chatPreferences, setChatPreferences] = useState(() => readLocalStorage(PREFERENCES_STORAGE_KEY, DEFAULT_CHAT_PREFERENCES))
  const [subjects, setSubjects] = useState([])
  const [courses, setCourses] = useState([])
  const [selectedSubjectId, setSelectedSubjectId] = useState('')
  const [selectedCourseId, setSelectedCourseId] = useState('')
  const [ragContextStatus, setRagContextStatus] = useState(null)
  const learnerLevel = diagnosticResult?.level ? getDisplayLevel(diagnosticResult.level) : ''

  useEffect(() => {
    try {
      const storedResult = localStorage.getItem('diagnosticResult')
      setDiagnosticResult(storedResult ? JSON.parse(storedResult) : null)
    } catch {
      setDiagnosticResult(null)
    }
    setChatPreferences(readLocalStorage(PREFERENCES_STORAGE_KEY, DEFAULT_CHAT_PREFERENCES))
  }, [])

  useEffect(() => {
    if (sessions.length === 0) {
      const firstSession = createSession()
      setSessions([firstSession])
      setActiveSessionId(firstSession.id)
      saveSessions([firstSession])
      return
    }

    saveSessions(sessions)
  }, [sessions])

  useEffect(() => () => clearStreamTimer(), [])

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchSubjects(), fetchCourses()])
      .then(([subjectsData, coursesData]) => {
        if (cancelled) return
        setSubjects(subjectsData)
        setCourses(coursesData)
      })
      .catch(() => {
        if (!cancelled) {
          setSubjects([])
          setCourses([])
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedCourseId) {
      setRagContextStatus(null)
      return
    }
    let cancelled = false
    fetchCourseRagStatus(selectedCourseId)
      .then((status) => {
        if (!cancelled) setRagContextStatus(status)
      })
      .catch(() => {
        if (!cancelled) setRagContextStatus({ index_status: 'failed', error: 'Contexte de cours indisponible.' })
      })
    return () => {
      cancelled = true
    }
  }, [selectedCourseId])

  const activeSession = sessions.find((session) => session.id === activeSessionId) || sessions[0] || createSession()
  const filteredSessions = useMemo(
    () => sessions.filter((session) => {
      const query = historySearch.trim().toLowerCase()
      if (!query) return true
      return `${displaySessionTitle(session)} ${displaySessionPreview(session)}`.toLowerCase().includes(query)
    }),
    [historySearch, sessions],
  )

  async function handleSend(event) {
    event?.preventDefault()
    await sendUserMessage(input)
  }

  function clearStreamTimer() {
    if (streamTimerRef.current) {
      window.clearTimeout(streamTimerRef.current)
      streamTimerRef.current = null
    }
  }

  async function sendUserMessage(rawMessage, options = {}) {
    const cleanMessage = rawMessage.trim()
    if (!diagnosticResult || !cleanMessage || isSending) {
      return
    }

    clearStreamTimer()
    stopStreamingRef.current = false
    setInput('')
    setIsSending(true)

    const userMessage = buildMessage('user', cleanMessage)
    const context = buildRecentContext(activeSession.messages)
    const nextSession = appendMessagesToSession(activeSession, [userMessage])
    updateSession(nextSession)

    try {
      const data = await sendChatMessage(cleanMessage, learnerLevel, context, {
        course_id: selectedCourseId ? Number(selectedCourseId) : null,
        subject_id: selectedSubjectId ? Number(selectedSubjectId) : null,
        session_id: activeSession.id,
      })
      const assistantMessage = buildMessage('assistant', '', {
        fullText: data.answer,
        mode: data.mode,
        sources: isRagMode(data.mode) ? data.sources || [] : [],
      })
      const sessionWithAssistant = appendMessagesToSession(nextSession, [assistantMessage])
      updateSession(sessionWithAssistant)
      if (chatPreferences.simulatedStreaming === false) {
        patchMessage(sessionWithAssistant.id, assistantMessage.id, { text: assistantMessage.fullText || assistantMessage.text || '' })
        setIsSending(false)
      } else {
        animateAssistantMessage(sessionWithAssistant.id, assistantMessage)
      }
      notifyChatUsage(options.regenerated)
    } catch {
      const errorMessage = buildMessage('assistant', "Impossible de contacter le service IA pour le moment.", {
        mode: 'error',
        sources: [],
      })
      updateSession(appendMessagesToSession(nextSession, [errorMessage]))
      setIsSending(false)
    }
  }

  function animateAssistantMessage(sessionId, assistantMessage) {
    const fullText = assistantMessage.fullText || assistantMessage.text || ''
    let cursor = 0

    function tick() {
      if (stopStreamingRef.current) {
        setIsSending(false)
        return
      }

      cursor = Math.min(fullText.length, cursor + STREAM_CHUNK_SIZE)
      patchMessage(sessionId, assistantMessage.id, { text: fullText.slice(0, cursor) })

      if (cursor >= fullText.length) {
        setIsSending(false)
        return
      }

      streamTimerRef.current = window.setTimeout(tick, STREAM_DELAY_MS)
    }

    tick()
  }

  function stopGenerating() {
    stopStreamingRef.current = true
    clearStreamTimer()
    setIsSending(false)
  }

  function regenerateLastAnswer() {
    const lastUserMessage = [...activeSession.messages].reverse().find((message) => message.role === 'user')
    if (!lastUserMessage) return

    const trimmedMessages = removeLastAssistantMessage(activeSession.messages)
    updateSession({
      ...activeSession,
      messages: trimmedMessages,
      lastMessage: trimmedMessages.at(-1)?.text || '',
      updatedAt: new Date().toISOString(),
    })
    sendUserMessage(lastUserMessage.text, { regenerated: true })
  }

  function startNewConversation() {
    clearStreamTimer()
    const newSession = createSession()
    setSessions((current) => [newSession, ...current])
    setActiveSessionId(newSession.id)
    setInput('')
    setIsSending(false)
  }

  function deleteSession(sessionId) {
    const nextSessions = sessions.filter((session) => session.id !== sessionId)
    if (nextSessions.length === 0) {
      const replacement = createSession()
      setSessions([replacement])
      setActiveSessionId(replacement.id)
      return
    }

    setSessions(nextSessions)
    if (activeSessionId === sessionId) {
      setActiveSessionId(nextSessions[0].id)
    }
  }

  function updateSession(nextSession) {
    setSessions((current) => {
      const exists = current.some((session) => session.id === nextSession.id)
      const nextSessions = exists
        ? current.map((session) => (session.id === nextSession.id ? nextSession : session))
        : [nextSession, ...current]
      return sortSessions(nextSessions)
    })
  }

  function patchMessage(sessionId, messageId, patch) {
    setSessions((current) => current.map((session) => {
      if (session.id !== sessionId) return session
      return {
        ...session,
        messages: session.messages.map((message) => (message.id === messageId ? { ...message, ...patch } : message)),
        updatedAt: new Date().toISOString(),
      }
    }))
  }

  function setAssistantFeedback(messageId, value) {
    const nextFeedback = { ...feedback, [messageId]: value }
    setFeedback(nextFeedback)
    localStorage.setItem(CHAT_FEEDBACK_KEY, JSON.stringify(nextFeedback))
  }

  function answerMiniQuiz(messageId, option, quiz) {
    if (quizAnswers[messageId]) return

    const isCorrect = option === quiz.answer
    setQuizAnswers((current) => ({ ...current, [messageId]: { option, isCorrect } }))
    if (isCorrect) {
      const nextXp = xp + 10
      setXp(nextXp)
      localStorage.setItem(CHAT_XP_KEY, JSON.stringify(nextXp))
    }
  }

  function exportConversation(format) {
    const content = format === 'markdown'
      ? buildMarkdownExport(activeSession)
      : buildTextExport(activeSession)
    const extension = format === 'markdown' ? 'md' : 'txt'
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${slugify(activeSession.title)}.${extension}`
    link.click()
    URL.revokeObjectURL(url)
  }

  function handleSubjectChange(event) {
    setSelectedSubjectId(event.target.value)
    setSelectedCourseId('')
    setRagContextStatus(null)
  }

  return (
    <section className="page-section chatbot-page">
      <div className="page-heading page-heading-row">
        <div>
          <h1>Chatbot IA</h1>
          <p>Posez vos questions sur les oeuvres, la langue, les figures de style et la production ecrite.</p>
        </div>
        <div className="chat-xp-pill">XP {xp}</div>
      </div>

      <div className="chat-layout chat-layout-enhanced">
        <aside className="chat-history-sidebar panel-card">
          <button className="primary-button" onClick={startNewConversation} type="button">
            <Plus size={18} />
            Nouvelle conversation
          </button>
          <label className="chat-search">
            <Search size={18} />
            <input
              onChange={(event) => setHistorySearch(event.target.value)}
              placeholder="Rechercher..."
              value={historySearch}
            />
          </label>
          <div className="chat-session-list">
            {filteredSessions.map((session) => (
              <article
                className={session.id === activeSessionId ? 'chat-session-item active' : 'chat-session-item'}
                key={session.id}
              >
                <button onClick={() => setActiveSessionId(session.id)} type="button">
                  <strong>{displaySessionTitle(session)}</strong>
                  <time>{formatDateTime(session.updatedAt)}</time>
                  <p>{displaySessionPreview(session)}</p>
                </button>
                <button aria-label="Supprimer la conversation" onClick={() => deleteSession(session.id)} type="button">
                  <Trash2 size={16} />
                </button>
              </article>
            ))}
          </div>
        </aside>

        <div className="chat-main">
          <div className="chat-toolbar panel-card">
            <div>
              <strong>{activeSession.title}</strong>
              <p>{activeSession.messages.length} message(s)</p>
            </div>
            <div>
              <button className="outline-button" onClick={() => exportConversation('markdown')} type="button">
                <Download size={18} />
                Export Markdown
              </button>
              <button className="outline-button" onClick={() => exportConversation('text')} type="button">
                <FileText size={18} />
                Export texte
              </button>
            </div>
          </div>

          <div className="chat-context-bar panel-card">
            <label>
              <span>Matière</span>
              <select onChange={handleSubjectChange} value={selectedSubjectId}>
                <option value="">Tous les supports autorisés</option>
                {subjects.map((subject) => (
                  <option key={subject.id} value={subject.id}>{subject.name}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Cours</span>
              <select onChange={(event) => setSelectedCourseId(event.target.value)} value={selectedCourseId}>
                <option value="">Aucun cours précis</option>
                {courses
                  .filter((course) => !selectedSubjectId || Number(course.subject_id) === Number(selectedSubjectId))
                  .map((course) => (
                    <option key={course.id} value={course.id}>{course.title}</option>
                  ))}
              </select>
            </label>
            <button className="outline-button" onClick={() => { setSelectedSubjectId(''); setSelectedCourseId(''); setRagContextStatus(null) }} type="button">
              Retirer le filtre
            </button>
            <p>
              Contexte : {selectedCourseId ? courses.find((course) => Number(course.id) === Number(selectedCourseId))?.title : selectedSubjectId ? subjects.find((subject) => Number(subject.id) === Number(selectedSubjectId))?.name : 'Tous les supports'}
              {ragContextStatus && <span> - État : {statusLabel(ragContextStatus.index_status)}</span>}
            </p>
          </div>

          <div className="chat-window panel-card">
            {!diagnosticResult && (
              <MessageBubble role="assistant" text="Passez d'abord le test diagnostique pour que je puisse adapter mes réponses à votre niveau." time="Maintenant" />
            )}
            {diagnosticResult && activeSession.messages.length === 0 && (
              <MessageBubble role="assistant" text="Bonjour ! Je suis votre assistant de francais pour la preparation au regional. Je peux vous aider avec les oeuvres, la langue, les figures de style, la methodologie et la production ecrite." time="Maintenant" />
            )}
            {diagnosticResult && activeSession.messages.map((message) => (
              <MessageBubble
                feedback={feedback[message.id]}
                key={message.id}
                message={message}
                onCopy={() => copyText(message.text)}
                onFeedback={setAssistantFeedback}
                onMiniQuizAnswer={answerMiniQuiz}
                onRegenerate={regenerateLastAnswer}
                onSuggestion={sendUserMessage}
                quizAnswer={quizAnswers[message.id]}
                role={message.role}
                showMiniQuiz={chatPreferences.chatbotMiniQuiz !== false}
                showSuggestions={chatPreferences.questionSuggestions !== false}
                sources={message.sources}
                text={message.text}
                time={formatMessageTime(message.time)}
              />
            ))}
          </div>

          {isSending && (
            <button className="outline-button stop-button" onClick={stopGenerating} type="button">
              <Square size={16} />
              Stop generating
            </button>
          )}

          {chatPreferences.questionSuggestions !== false && <div className="suggestion-row">
            {['Explique-moi ce passage de La Boite a merveilles.', 'Quelle figure de style est utilisee dans cette phrase ?', 'Corrige ma reponse a cette question.', 'Aide-moi a preparer une production ecrite.', 'Fais-moi reviser mes points faibles.', 'Pose-moi cinq questions sur Antigone.'].map((item) => (
              <button disabled={!diagnosticResult || isSending} key={item} onClick={() => sendUserMessage(item)} type="button">{item}</button>
            ))}
          </div>}

          <form className="chat-form" onSubmit={handleSend}>
            <input
              disabled={!diagnosticResult || isSending}
              onChange={(event) => setInput(event.target.value)}
              placeholder={diagnosticResult ? 'Écrivez votre message...' : 'Passez le test diagnostique pour activer le chatbot'}
              value={input}
            />
            <button className="send-button" disabled={!diagnosticResult || !input.trim() || isSending} type="submit" aria-label="Envoyer"><Send size={24} /></button>
          </form>
          <p className="chat-disclaimer">EduMentor IA peut faire des erreurs. Vérifiez les informations importantes.</p>
        </div>

        <aside className="chat-side panel-card">
          <h2>À propos de l'assistant</h2>
          <p>Je suis votre assistant de francais pour la 1ere Bac. Je peux vous aider a comprendre les oeuvres, analyser une phrase, corriger une reponse et preparer une production ecrite.</p>
          <h3>Niveau utilisé</h3>
          <p>{diagnosticResult ? learnerLevel : 'Test diagnostique non encore passé'}</p>
          <h3>Accompagnement</h3>
          <p>Oeuvres <span>Programme regional</span></p>
          <p>Langue <span>Exercices guides</span></p>
          <p>Methodologie <span>Conseils adaptes</span></p>
          <h3>Exemples</h3>
          {["Explique-moi le role de Creon dans Antigone.", 'Quelle figure de style est utilisee dans cette phrase ?', 'Aide-moi a rediger une introduction.'].map((item) => (
            <p className="sample-question" key={item}><Sparkles size={18} />{item}</p>
          ))}
        </aside>
      </div>
    </section>
  )
}

function MessageBubble({
  feedback,
  message = {},
  onCopy,
  onFeedback,
  onMiniQuizAnswer,
  onRegenerate,
  onSuggestion,
  quizAnswer,
  role,
  showMiniQuiz = true,
  showSuggestions = true,
  sources = [],
  text,
  time,
}) {
  const isAssistant = role === 'assistant'
  const mode = message.mode
  const suggestions = isAssistant && showSuggestions ? buildSuggestions(text) : []
  const quiz = isAssistant && showMiniQuiz && (isRagMode(mode) || ['general', 'general_education', 'general_french'].includes(mode)) ? buildMiniQuiz(text) : null

  return (
    <div className={`chat-message ${role}`}>
      {isAssistant && <span className="bot-icon"><Brain size={22} /></span>}
      <div>
        {isAssistant && (
          <div className="message-topline">
            <span className={`mode-badge ${mode || 'general'}`}>{modeLabel(mode)}</span>
            <div className="message-actions">
              <button onClick={onCopy} type="button"><Clipboard size={15} />Copier</button>
              <button onClick={onRegenerate} type="button"><RefreshCcw size={15} />Régénérer</button>
            </div>
          </div>
        )}
        <MarkdownContent text={text} />
        {isAssistant && isRagMode(mode) && sources.length > 0 && (
          <div className="chat-sources">
            <strong>Sources utilisées</strong>
            {sources.map((source, index) => (
              <a href={sourceUrl(source)} key={`${source.file_name || source.pdf_name}-${source.page_start || source.page_number}-${index}`} rel="noreferrer" target="_blank">
                {source.file_name || source.pdf_name} · {source.course_title || source.course_name} · {source.subject_name || 'Matière'} · page {source.page_start || source.page_number || '-'}
                {source.excerpt && <span>{shortPreview(source.excerpt, 120)}</span>}
              </a>
            ))}
          </div>
        )}
        {isAssistant && suggestions.length > 0 && (
          <div className="assistant-suggestions">
            {suggestions.map((suggestion) => (
              <button key={suggestion} onClick={() => onSuggestion(suggestion)} type="button">{suggestion}</button>
            ))}
          </div>
        )}
        {quiz && (
          <MiniQuiz
            answer={quizAnswer}
            messageId={message.id}
            onAnswer={onMiniQuizAnswer}
            quiz={quiz}
          />
        )}
        {isAssistant && (
          <div className="feedback-row">
            <button className={feedback === 'like' ? 'active' : ''} onClick={() => onFeedback(message.id, 'like')} type="button"><ThumbsUp size={16} /></button>
            <button className={feedback === 'dislike' ? 'active' : ''} onClick={() => onFeedback(message.id, 'dislike')} type="button"><ThumbsDown size={16} /></button>
          </div>
        )}
        <time>{time}</time>
      </div>
    </div>
  )
}

function MiniQuiz({ answer, messageId, onAnswer, quiz }) {
  return (
    <div className="mini-quiz">
      <strong>🎯 Testez votre compréhension</strong>
      <p>{quiz.question}</p>
      <div>
        {quiz.options.map((option) => (
          <button
            className={answer?.option === option ? 'selected' : ''}
            disabled={Boolean(answer)}
            key={option}
            onClick={() => onAnswer(messageId, option, quiz)}
            type="button"
          >
            {option}
          </button>
        ))}
      </div>
      {answer && (
        <p className={answer.isCorrect ? 'quiz-correct' : 'quiz-wrong'}>
          {answer.isCorrect ? '+10 XP · Bonne réponse.' : `Correction : ${quiz.answer}.`} {quiz.explanation}
        </p>
      )}
    </div>
  )
}

function MarkdownContent({ text }) {
  const blocks = parseMarkdown(text || '')
  return (
    <div className="markdown-content">
      {blocks.map((block, index) => {
        if (block.type === 'heading') return <h3 key={index}>{block.text}</h3>
        if (block.type === 'list') return <ul key={index}>{block.items.map((item) => <li key={item}>{renderInlineMarkdown(item)}</li>)}</ul>
        if (block.type === 'code') return <pre key={index}><code>{block.text}</code></pre>
        return <p key={index}>{renderInlineMarkdown(block.text)}</p>
      })}
    </div>
  )
}

function parseMarkdown(text) {
  const lines = text.split('\n')
  const blocks = []
  let paragraph = []
  let list = []
  let code = []
  let inCode = false

  function flushParagraph() {
    if (paragraph.length) {
      blocks.push({ type: 'paragraph', text: paragraph.join(' ') })
      paragraph = []
    }
  }

  function flushList() {
    if (list.length) {
      blocks.push({ type: 'list', items: list })
      list = []
    }
  }

  lines.forEach((line) => {
    if (line.trim().startsWith('```')) {
      if (inCode) {
        blocks.push({ type: 'code', text: code.join('\n') })
        code = []
        inCode = false
      } else {
        flushParagraph()
        flushList()
        inCode = true
      }
      return
    }

    if (inCode) {
      code.push(line)
      return
    }

    if (line.startsWith('#')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'heading', text: line.replace(/^#+\s*/, '') })
      return
    }

    if (/^\s*[-*]\s+/.test(line)) {
      flushParagraph()
      list.push(line.replace(/^\s*[-*]\s+/, ''))
      return
    }

    if (!line.trim()) {
      flushParagraph()
      flushList()
      return
    }

    paragraph.push(line.trim())
  })

  flushParagraph()
  flushList()
  if (code.length) blocks.push({ type: 'code', text: code.join('\n') })
  return blocks
}

function renderInlineMarkdown(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>
    }
    return part
  })
}

function createSession() {
  const now = new Date().toISOString()
  return {
    id: createId(),
    title: 'Nouvelle conversation',
    createdAt: now,
    updatedAt: now,
    lastMessage: '',
    messages: [],
  }
}

function buildMessage(role, text, extra = {}) {
  return {
    id: createId(),
    role,
    text,
    time: new Date().toISOString(),
    sources: [],
    ...extra,
  }
}

function appendMessagesToSession(session, messages) {
  const nextMessages = [...session.messages, ...messages]
  const firstUserMessage = nextMessages.find((message) => message.role === 'user')
  const lastUserMessage = [...nextMessages].reverse().find((message) => message.role === 'user')
  const lastMessage = shortPreview(lastUserMessage?.text || session.lastMessage || '')
  return {
    ...session,
    title: firstUserMessage ? titleFromMessage(firstUserMessage.text) : session.title,
    updatedAt: new Date().toISOString(),
    lastMessage,
    messages: nextMessages,
  }
}

function removeLastAssistantMessage(messages) {
  const nextMessages = [...messages]
  const index = nextMessages.map((message) => message.role).lastIndexOf('assistant')
  if (index >= 0) nextMessages.splice(index, 1)
  return nextMessages
}

function buildRecentContext(messages) {
  return messages.slice(-6).map((message) => ({
    role: message.role,
    content: message.text,
  }))
}

function buildSuggestions(text) {
  const normalized = normalizeText(text)
  if (normalized.includes('antigone') || normalized.includes('creon')) {
    return ['Resume le conflit', 'Explique Creon', 'Pose-moi 3 questions']
  }
  if (normalized.includes('figure') || normalized.includes('metaphore') || normalized.includes('comparaison')) {
    return ['Donne un exemple', 'Explique son effet', 'Propose un exercice']
  }
  if (normalized.includes('production') || normalized.includes('redaction')) {
    return ['Propose un plan', 'Aide-moi a introduire', 'Donne des connecteurs']
  }
  return ['Donne un exemple', 'Resume en 3 points', 'Propose un mini exercice']
}

function buildMiniQuiz(text) {
  const normalized = normalizeText(text)
  if (normalized.includes('figure') || normalized.includes('metaphore') || normalized.includes('comparaison')) {
    return {
      question: 'Que faut-il toujours expliquer apres avoir nomme une figure de style ?',
      options: ['Son effet dans le texte', 'Le nombre de pages', 'Le nom du correcteur', 'La couleur de la couverture'],
      answer: 'Son effet dans le texte',
      explanation: 'Identifier la figure ne suffit pas : il faut expliquer ce qu elle apporte au sens.',
    }
  }
  if (normalized.includes('antigone') || normalized.includes('creon')) {
    return {
      question: 'Dans une reponse sur Antigone, que faut-il ajouter pour justifier son idee ?',
      options: ['Un indice du texte', 'Une information inventee', 'Un avis sans preuve', 'Une phrase hors sujet'],
      answer: 'Un indice du texte',
      explanation: 'Une bonne reponse de comprehension doit etre justifiee par un element precis du passage.',
    }
  }
  return {
    question: 'Quelle bonne pratique aide a reussir une question de regional ?',
    options: ['Lire la consigne puis justifier', 'Repondre sans lire', 'Inventer une citation', 'Ignorer le bareme'],
    answer: 'Lire la consigne puis justifier',
    explanation: 'La consigne indique le type de reponse attendu et la justification montre votre comprehension.',
  }
}

function notifyChatUsage(regenerated) {
  if (!regenerated) {
    addNotification({
      type: 'chatbot',
      title: 'Nouvelle réponse pédagogique générée',
      message: 'Le chatbot a généré une réponse adaptée à votre question.',
    })
  }
}

function sourceUrl(source) {
  const page = source.page_start || source.page_number
  const pageAnchor = page ? `#page=${page}` : ''
  if (source.file_url) return `${API_BASE_URL}${source.file_url}${pageAnchor}`
  return `${API_BASE_URL}/docs/courses/${encodeURIComponent(source.file_name || source.pdf_name)}${pageAnchor}`
}

function modeLabel(mode) {
  if (mode === 'rag_course') return 'Réponse basée sur le cours'
  if (mode === 'rag_subject') return 'Réponse basée sur la matière'
  if (mode === 'rag_semantic') return 'Réponse basée sur les supports'
  if (mode === 'general_education') return 'Réponse générale'
  if (mode === 'general_french') return 'Réponse générale'
  if (mode === 'targeted_practice') return 'Entrainement personnalisé'
  if (mode === 'out_of_scope') return 'Assistant EduMentor'
  if (mode === 'social') return 'Assistant EduMentor'
  if (mode === 'error') return 'Service indisponible'
  return 'Réponse générale'
}

function isRagMode(mode) {
  return ['rag_semantic', 'rag_course', 'rag_subject'].includes(mode)
}

function statusLabel(status) {
  if (status === 'ready') return 'Indexé'
  if (status === 'processing') return 'Indexation en cours'
  if (status === 'pending') return 'En attente'
  if (status === 'outdated') return 'Réindexation nécessaire'
  if (status === 'failed') return 'Échec'
  return status || 'Non indexé'
}

function readSessions() {
  const sessions = readLocalStorage(CHAT_SESSIONS_KEY, [])
  return Array.isArray(sessions) ? sortSessions(sessions) : []
}

function saveSessions(sessions) {
  localStorage.setItem(CHAT_SESSIONS_KEY, JSON.stringify(sortSessions(sessions)))
}

function sortSessions(sessions) {
  return [...sessions].sort((first, second) => new Date(second.updatedAt) - new Date(first.updatedAt))
}

function readLocalStorage(key, fallback) {
  try {
    const storedValue = localStorage.getItem(key)
    return storedValue ? JSON.parse(storedValue) : fallback
  } catch {
    return fallback
  }
}

function copyText(text) {
  navigator.clipboard?.writeText(text)
}

function buildMarkdownExport(session) {
  return [`# ${session.title}`, '', ...session.messages.map((message) => `## ${message.role}\n\n${message.text}`)].join('\n\n')
}

function buildTextExport(session) {
  return session.messages.map((message) => `${message.role.toUpperCase()}: ${message.text}`).join('\n\n')
}

function titleFromMessage(message) {
  const normalized = normalizeText(message)
  if (normalized.includes('antigone')) return 'Antigone'
  if (normalized.includes('figure')) return 'Figure de style'
  if (normalized.includes('production')) return 'Production ecrite'
  if (normalized.includes('bonjour') || normalized.includes('salut') || normalized.includes('hello') || normalized.includes('hi')) return 'Bonjour'

  const words = String(message || '')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 3)

  return words.join(' ') || 'Nouvelle discussion'
}

function displaySessionTitle(session) {
  return titleFromMessage(session.messages?.find((message) => message.role === 'user')?.text || session.title)
}

function displaySessionPreview(session) {
  return shortPreview(session.lastMessage || session.messages?.find((message) => message.role === 'user')?.text || 'Conversation vide')
}

function shortPreview(value, maxLength = 20) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (!text) return 'Conversation vide'
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text
}

function slugify(value) {
  return normalizeText(value).replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'conversation'
}

function createId() {
  return window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function formatMessageTime(time) {
  if (!time) return 'Maintenant'
  const date = new Date(time)
  if (Number.isNaN(date.getTime())) return time
  return new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' }).format(date)
}

function formatDateTime(time) {
  const date = new Date(time)
  if (Number.isNaN(date.getTime())) return 'Maintenant'
  return new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

function getDisplayLevel(level) {
  const normalizedLevel = normalizeLevel(level)
  if (normalizedLevel === 'avance') return 'Avancé'
  if (normalizedLevel === 'intermediaire') return 'Intermédiaire'
  return 'Débutant'
}

function normalizeLevel(level) {
  const normalized = normalizeText(level)
  if (normalized.includes('debut')) return 'debutant'
  if (normalized.includes('avance') || normalized.includes('avanc')) return 'avance'
  return normalized.includes('inter') ? 'intermediaire' : ''
}

function normalizeText(value) {
  return String(value || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
}

export default ChatbotPage
