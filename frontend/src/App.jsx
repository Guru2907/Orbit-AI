import { useState, useEffect } from 'react'
import Landing from './components/Landing.jsx'
import AuthPage from './components/AuthPage.jsx'
import ChatPage from './components/ChatPage.jsx'
import { MESSAGES } from './apiClient.js'
import { isTokenExpired } from './session.js'

export default function App() {
  const [page, setPage] = useState('landing')
  const [authMode, setAuthMode] = useState('login')
  const [authNotice, setAuthNotice] = useState('')
  const [token, setToken] = useState(null)
  const [email, setEmail] = useState(null)

  useEffect(() => {
    const savedToken = localStorage.getItem('orbit_token')
    const savedEmail = localStorage.getItem('orbit_email')
    if (savedToken && savedEmail) {
      if (isTokenExpired(savedToken)) {
        clearSession()
        return
      }
      setToken(savedToken)
      setEmail(savedEmail)
      setPage('chat')
    }
  }, [])

  function clearSession() {
    localStorage.removeItem('orbit_token')
    localStorage.removeItem('orbit_email')
    setToken(null)
    setEmail(null)
  }

  function handleNavigate(nextPage, mode) {
    if (mode) setAuthMode(mode)
    setAuthNotice('')
    setPage(nextPage)
  }

  function handleAuthSuccess(newToken, newEmail) {
    localStorage.setItem('orbit_token', newToken)
    localStorage.setItem('orbit_email', newEmail)
    setToken(newToken)
    setEmail(newEmail)
    setAuthNotice('')
    setPage('chat')
  }

  function handleLogout() {
    clearSession()
    setPage('landing')
  }

  function handleSessionExpired() {
    clearSession()
    setAuthMode('login')
    setAuthNotice(MESSAGES.sessionExpired)
    setPage('auth')
  }

  if (page === 'chat' && token) {
    return <ChatPage token={token} email={email} onLogout={handleLogout} onSessionExpired={handleSessionExpired} />
  }

  if (page === 'auth') {
    return (
      <AuthPage
        initialMode={authMode}
        notice={authNotice}
        onAuthSuccess={handleAuthSuccess}
        onBack={() => setPage('landing')}
      />
    )
  }

  return <Landing onNavigate={handleNavigate} />
}
