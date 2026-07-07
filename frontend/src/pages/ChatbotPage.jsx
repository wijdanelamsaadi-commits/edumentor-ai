import { Brain, Paperclip, Plus, Send, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLearning } from '../hooks/useLearning.js'

function ChatbotPage() {
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [diagnosticResult, setDiagnosticResult] = useState(null)
  const { messages, sendMessage } = useLearning()
  const learnerLevel = diagnosticResult?.level ? getDisplayLevel(diagnosticResult.level) : ''

  useEffect(() => {
    try {
      const storedResult = localStorage.getItem('diagnosticResult')
      setDiagnosticResult(storedResult ? JSON.parse(storedResult) : null)
    } catch {
      setDiagnosticResult(null)
    }
  }, [])

  async function handleSend(event) {
    event.preventDefault()

    if (!diagnosticResult || !input.trim() || isSending) {
      return
    }

    setIsSending(true)
    await sendMessage(input, learnerLevel)
    setInput('')
    setIsSending(false)
  }

  async function handleSuggestion(text) {
    if (!diagnosticResult || isSending) {
      return
    }

    setIsSending(true)
    await sendMessage(text, learnerLevel)
    setIsSending(false)
  }

  return (
    <section className="page-section chatbot-page">
      <div className="page-heading">
        <h1>Chatbot IA</h1>
        <p>Posez toutes vos questions sur l'intelligence artificielle.</p>
      </div>
      <div className="chat-layout">
        <div className="chat-main">
          <div className="chat-window">
            {!diagnosticResult && (
              <MessageBubble role="assistant" text="Passez d'abord le test diagnostique pour que je puisse adapter mes réponses à votre niveau." time="Maintenant" />
            )}
            {diagnosticResult && messages.map((message, index) => (
              <MessageBubble
                key={`${message.role}-${index}`}
                role={message.role}
                sources={message.sources}
                text={message.text}
                time={formatMessageTime(message.time)}
              />
            ))}
          </div>
          <div className="suggestion-row">
            {['Explique le deep learning', 'Différence IA, ML, DL', "Exemples d'utilisation", 'Autres suggestions'].map((item) => (
              <button disabled={!diagnosticResult || isSending} key={item} onClick={() => handleSuggestion(item)} type="button">{item}</button>
            ))}
          </div>
          <form className="chat-form" onSubmit={handleSend}>
            <input
              disabled={!diagnosticResult}
              onChange={(event) => setInput(event.target.value)}
              placeholder={diagnosticResult ? 'Écrivez votre message...' : 'Passez le test diagnostique pour activer le chatbot'}
              value={input}
            />
            <div className="chat-tools"><Plus size={24} /><Paperclip size={24} /><Sparkles size={24} /></div>
            <button className="send-button" disabled={!diagnosticResult || !input.trim() || isSending} type="submit" aria-label="Envoyer"><Send size={24} /></button>
          </form>
          <p className="chat-disclaimer">EduMentor IA peut faire des erreurs. Vérifiez les informations importantes.</p>
        </div>
        <aside className="chat-side panel-card">
          <h2>À propos de l'assistant</h2>
          <p>Je suis votre assistant IA personnel. Je peux vous aider à comprendre les concepts, résoudre des problèmes et vous accompagner dans votre apprentissage.</p>
          <h3>Niveau utilisé</h3>
          <p>{diagnosticResult ? learnerLevel : 'Test diagnostique non encore passé'}</p>
          <h3>Exemples de questions</h3>
          {["Qu'est-ce que l'IA générative ?", 'Comment fonctionne un réseau de neurones ?', 'Donne-moi un exemple de prompt efficace.', "Quelles sont les applications de l'IA dans la santé ?"].map((item) => (
            <p className="sample-question" key={item}><Sparkles size={18} />{item}</p>
          ))}
          <h3>Vos conversations récentes</h3>
          {diagnosticResult && messages.filter((message) => message.role === 'user').slice(-2).map((message, index) => (
            <p key={`${message.text}-${index}`}>{message.text} <span>Maintenant</span></p>
          ))}
          {!diagnosticResult && <p>Passez le test diagnostique <span>À faire</span></p>}
          <button type="button">Voir tout l'historique →</button>
        </aside>
      </div>
    </section>
  )
}

function MessageBubble({ role, sources = [], text, time }) {
  return (
    <div className={`chat-message ${role}`}>
      {role === 'assistant' && <span className="bot-icon"><Brain size={22} /></span>}
      <div>
        <p>{text}</p>
        {role === 'assistant' && sources.length > 0 && (
          <div className="chat-sources">
            <strong>Sources utilisées</strong>
            {sources.map((source, index) => (
              <p key={`${source.file_name}-${source.page_number}-${index}`}>
                {source.file_name} · {source.course_name} · page {source.page_number}
              </p>
            ))}
          </div>
        )}
        <time>{time}</time>
      </div>
    </div>
  )
}

function formatMessageTime(time) {
  if (!time) return 'Maintenant'

  const date = new Date(time)

  if (Number.isNaN(date.getTime())) {
    return time
  }

  return new Intl.DateTimeFormat('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function getDisplayLevel(level) {
  const normalizedLevel = normalizeLevel(level)
  if (normalizedLevel === 'avance') return 'Avancé'
  if (normalizedLevel === 'intermediaire') return 'Intermédiaire'
  return 'Débutant'
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
  return normalized.includes('inter') ? 'intermediaire' : ''
}

export default ChatbotPage
