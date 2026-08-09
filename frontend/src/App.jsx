import { useState, useEffect } from 'react'
import Landing from './components/Landing.jsx'
import AuthPage from './components/AuthPage.jsx'
import ChatPage from './components/ChatPage.jsx'

export default function App() {
  const [page, setPage] = useState('landing')
  const [authMode, setAuthMode] = useState('login')
  const [token, setToken] = useState(null)
  const [email, setEmail] = useState(null)

  useEffect(() => {
    const savedToken = localStorage.getItem('orbit_token')
    const savedEmail = localStorage.getItem('orbit_email')
    if (savedToken && savedEmail) {
      setToken(savedToken)
      setEmail(savedEmail)
      setPage('chat')
    }
  }, [])

  function handleNavigate(nextPage, mode) {
    if (mode) setAuthMode(mode)
    setPage(nextPage)
  }

  function handleAuthSuccess(newToken, newEmail) {
    localStorage.setItem('orbit_token', newToken)
    localStorage.setItem('orbit_email', newEmail)
    setToken(newToken)
    setEmail(newEmail)
    setPage('chat')
  }

  function handleLogout() {
    localStorage.removeItem('orbit_token')
    localStorage.removeItem('orbit_email')
    setToken(null)
    setEmail(null)
    setPage('landing')
  }

  if (page === 'chat' && token) {
    return <ChatPage token={token} email={email} onLogout={handleLogout} />
  }

  if (page === 'auth') {
    return (
      <AuthPage
        initialMode={authMode}
        onAuthSuccess={handleAuthSuccess}
        onBack={() => setPage('landing')}
      />
    )
  }

  return <Landing onNavigate={handleNavigate} />
}