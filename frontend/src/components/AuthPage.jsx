import { useState } from 'react'
import OrbitMark from './OrbitMark.jsx'
import { login, signup } from '../api.js'

export default function AuthPage({ initialMode, onAuthSuccess, onBack }) {
  const [mode, setMode] = useState(initialMode || 'login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const action = mode === 'login' ? login : signup
      const data = await action(email, password)
      onAuthSuccess(data.token, data.email)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-6">
      <div className="w-full max-w-sm">
        <button onClick={onBack} className="mb-8 flex items-center gap-2 text-sm text-inksoft hover:text-ink transition">
          <OrbitMark size={20} />
          <span className="font-display font-medium">Flowspace</span>
        </button>

        <div className="rounded-2xl border border-line bg-surface p-7">
          <div className="mb-6 flex rounded-full bg-bg p-1">
            <button onClick={() => setMode('login')} className={`flex-1 rounded-full py-2 text-sm font-medium transition ${mode === 'login' ? 'bg-surface shadow text-ink' : 'text-inksoft'}`}>
              Log in
            </button>
            <button onClick={() => setMode('signup')} className={`flex-1 rounded-full py-2 text-sm font-medium transition ${mode === 'signup' ? 'bg-surface shadow text-ink' : 'text-inksoft'}`}>
              Sign up
            </button>
          </div>

          <h1 className="font-display text-xl font-semibold text-ink">
            {mode === 'login' ? 'Welcome back' : 'Create your account'}
          </h1>
          <p className="mt-1 text-[13.5px] text-inksoft">
            {mode === 'login' ? 'Log in to chat with Orbit.' : 'Takes about ten seconds.'}
          </p>

          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            <div>
              <label className="mb-1.5 block text-[13px] font-medium text-ink">Email</label>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com"
                className="w-full rounded-xl border border-line bg-bg px-3.5 py-2.5 text-sm text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 transition" />
            </div>
            <div>
              <label className="mb-1.5 block text-[13px] font-medium text-ink">Password</label>
              <input type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••"
                className="w-full rounded-xl border border-line bg-bg px-3.5 py-2.5 text-sm text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 transition" />
            </div>

            {error && (
              <p className="rounded-lg bg-accent/10 px-3 py-2 text-[13px] text-accent">{error}</p>
            )}

            <button type="submit" disabled={loading} className="w-full rounded-xl bg-brand py-2.5 text-sm font-medium text-white hover:opacity-90 transition disabled:opacity-50">
              {loading ? 'Please wait…' : mode === 'login' ? 'Log in' : 'Create account'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}