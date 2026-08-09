import { useState, useRef, useEffect } from 'react'
import OrbitMark from './OrbitMark.jsx'
import { askOrbit } from '../api.js'

const quickPrompts = [
  'What are the pricing plans?',
  'How do I cancel my subscription?',
  'How do I invite a teammate?',
  'What are the API rate limits?',
  'How do I enable two-factor authentication?',
]

export default function ChatPage({ token, email, onLogout }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function sendQuestion(question) {
    if (!question.trim() || loading) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', text: question }])
    setLoading(true)
    try {
      const data = await askOrbit(question, token)
      setMessages((prev) => [...prev, { role: 'bot', text: data.answer, sources: data.sources }])
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'bot', text: err.message, sources: [], isError: true }])
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    sendQuestion(input)
  }

  return (
    <div className="flex h-screen flex-col bg-bg">
      <header className="flex items-center justify-between border-b border-line bg-surface px-6 py-4">
        <div className="flex items-center gap-2.5">
          <OrbitMark size={26} spinning={loading} />
          <div>
            <p className="font-display text-[15px] font-semibold leading-none text-ink">Orbit</p>
            <p className="mt-0.5 text-[12px] text-inksoft">Flowspace support assistant</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden font-mono text-[12px] text-inksoft sm:inline">{email}</span>
          <button onClick={onLogout} className="rounded-full border border-line px-3.5 py-1.5 text-[13px] font-medium text-ink hover:bg-bg transition">
            Log out
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-2xl">
          {messages.length === 0 && (
            <div className="mt-10 text-center">
              <OrbitMark size={40} />
              <p className="mx-auto mt-4 max-w-xs text-[14px] text-inksoft">
                Ask about pricing, cancellations, invites, or anything else in Flowspace's support docs.
              </p>
            </div>
          )}

          <div className="space-y-5">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-[14.5px] leading-relaxed ${
                  m.role === 'user' ? 'bg-brand text-white' : m.isError ? 'border border-accent/30 bg-accent/5 text-ink' : 'border border-line bg-surface text-ink'
                }`}>
                  <p className="whitespace-pre-wrap">{m.text}</p>
                  {m.sources && m.sources.length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {m.sources.map((s) => (
                        <span key={s} className="rounded-full bg-brandsoft px-2 py-0.5 font-mono text-[11px] text-brand">{s}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-2xl border border-line bg-surface px-4 py-3">
                  <OrbitMark size={16} spinning />
                  <span className="text-[13px] text-inksoft">Orbit is thinking…</span>
                </div>
              </div>
            )}
          </div>
          <div ref={bottomRef} />
        </div>
      </div>

      {messages.length === 0 && (
        <div className="mx-auto mb-3 flex max-w-2xl flex-wrap gap-2 px-6">
          {quickPrompts.map((q) => (
            <button key={q} onClick={() => sendQuestion(q)} className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-[12.5px] text-inksoft hover:border-brand hover:text-brand transition">
              {q}
            </button>
          ))}
        </div>
      )}

      <form onSubmit={handleSubmit} className="border-t border-line bg-surface px-6 py-4">
        <div className="mx-auto flex max-w-2xl items-center gap-3">
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask Orbit about Flowspace…"
            className="flex-1 rounded-full border border-line bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 transition" />
          <button type="submit" disabled={loading || !input.trim()} className="rounded-full bg-brand px-5 py-2.5 text-sm font-medium text-white hover:opacity-90 transition disabled:opacity-40">
            Send
          </button>
        </div>
      </form>
    </div>
  )
}