import React, { useEffect, useState, useCallback } from 'react'  // ← useCallback ajouté
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore, apiFetch } from './store/auth'

import { LoginPage }          from './pages/LoginPage'
import { ChangePasswordPage } from './pages/ChangePasswordPage'
import { DashboardPage }      from './pages/DashboardPage'
import { ShipmentsPage }      from './pages/ShipmentsPage'
import { KPIDetailPage }      from './pages/KPIDetailPage'
import { CarriersPage }       from './pages/CarriersPage'
import { PredictionPage }     from './pages/PredictionPage'
import { MessagesPage }       from './pages/MessagesPage'
import { AdminPage }          from './pages/AdminPage'
import { SettingsPage }       from './pages/SettingsPage'
import { SplashScreen }       from './components/SplashScreen/SplashScreen'

/* ─── Loading Screen ─────────────────────────────────────────────────────── */
const LoadingScreen = () => (
  <div style={{
    minHeight: '100vh', display: 'flex', alignItems: 'center',
    justifyContent: 'center', background: 'var(--color-bg)',
    flexDirection: 'column', gap: 16,
  }}>
    <div style={{
      width: 40, height: 40,
      border: '2px solid var(--color-border)',
      borderTopColor: 'var(--color-accent)',
      borderRadius: '50%',
      animation: 'spin 0.8s linear infinite',
    }} />
    <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    <p style={{ color: 'var(--color-text-tertiary)', fontSize: 13 }}>Chargement...</p>
  </div>
)

/* ─── Auth Guard ─────────────────────────────────────────────────────────── */
const RequireAuth = ({ children, roles }) => {
  const { user, token } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  if (!user)  return <LoadingScreen />
  const exempts = ['/change-password', '/settings']
  if (user.doit_changer_mdp && !exempts.includes(window.location.pathname)) {
    return <Navigate to="/change-password" replace />
  }
  if (roles && !roles.includes(user.role)) {
    const fallback = user.role === 'Administrateur' ? '/admin' : '/dashboard'
    return <Navigate to={fallback} replace />
  }
  return children
}

/* ─── App ────────────────────────────────────────────────────────────────── */
export default function App() {
  const { token, user, setUser, logout } = useAuthStore()

  // ← tous les états en haut, avant tout return
  const [bootstrapped,   setBootstrapped] = useState(false)
  const [showSplash,     setShowSplash]   = useState(true)
  const handleSplashDone = useCallback(() => setShowSplash(false), [])

  // Restaurer la session depuis le token (en parallèle du splash)
  useEffect(() => {
    if (!token) { setBootstrapped(true); return }
    apiFetch('/admin/me')
      .then(me => {
        setUser({
          id:               me.id,
          nom:              me.nom,
          prenom:           me.prenom,
          role:             me.nom_role,
          doit_changer_mdp: me.doit_changer_mdp,
        })
      })
      .catch(() => logout())
      .finally(() => setBootstrapped(true))
  }, [])

  // ← splash en premier, avant tout le reste
  if (showSplash)    return <SplashScreen onDone={handleSplashDone} />
  if (!bootstrapped) return <LoadingScreen />

  const operateurs   = ['Control Tower Team', 'Performance Managers Team']
  const avecMessages = ['Control Tower Team', 'Performance Managers Team', 'Administrateur']
  const admins       = ['Administrateur']
  const defaultRoute = user?.role === 'Administrateur' ? '/admin' : '/dashboard'

  return (
    <Routes>
      <Route path="/login"
        element={token ? <Navigate to={defaultRoute} replace /> : <LoginPage />}
      />
      <Route path="/change-password" element={<ChangePasswordPage />} />

      <Route path="/dashboard"
        element={<RequireAuth roles={operateurs}><DashboardPage /></RequireAuth>}
      />
      <Route path="/shipments"
        element={<RequireAuth roles={operateurs}><ShipmentsPage /></RequireAuth>}
      />
      <Route path="/kpis"
        element={<RequireAuth roles={operateurs}><KPIDetailPage /></RequireAuth>}
      />
      <Route path="/carriers"
        element={<RequireAuth roles={operateurs}><CarriersPage /></RequireAuth>}
      />
      <Route path="/prediction"
        element={<RequireAuth roles={operateurs}><PredictionPage /></RequireAuth>}
      />

      <Route path="/messages"
        element={<RequireAuth roles={avecMessages}><MessagesPage /></RequireAuth>}
      />
      <Route path="/admin"
        element={<RequireAuth roles={admins}><AdminPage /></RequireAuth>}
      />
      <Route path="/settings"
        element={<RequireAuth roles={[...operateurs, ...admins]}><SettingsPage /></RequireAuth>}
      />

      <Route path="/"  element={<Navigate to={token ? defaultRoute : '/login'} replace />} />
      <Route path="*"  element={<Navigate to={token ? defaultRoute : '/login'} replace />} />
    </Routes>
  )
}