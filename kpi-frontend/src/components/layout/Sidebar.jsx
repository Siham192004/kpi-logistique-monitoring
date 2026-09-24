import React, { useState, useEffect } from 'react'  // ← ajout useEffect
import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, Ship, BarChart3, Users, MessageSquare,
  Brain, ChevronLeft, ChevronRight, LogOut, Anchor, Settings
} from 'lucide-react'
import { useAuthStore, apiFetch } from '../../store/auth'  // ← ajout apiFetch
import styles from './Sidebar.module.css'
import { useSidebar } from './SidebarContext'

const NAV_ITEMS = [
  { label: 'Dashboard', path: '/dashboard', icon: LayoutDashboard, roles: ['Control Tower Team', 'Performance Managers Team'] },
  { label: 'Shipments', path: '/shipments', icon: Ship, roles: ['Control Tower Team', 'Performance Managers Team'] },
  { label: 'KPI Détail',  path: '/kpis',      icon: BarChart3, roles: ['Control Tower Team', 'Performance Managers Team'] },
  { label: 'Carriers',   path: '/carriers',   icon: Anchor, roles: ['Control Tower Team', 'Performance Managers Team'] },
  { label: 'Prédiction', path: '/prediction', icon: Brain, roles: ['Control Tower Team', 'Performance Managers Team'] },
  { label: 'Admin',      path: '/admin',      icon: Users, roles: ['Administrateur'] },
  { label: 'Messages',   path: '/messages',   icon: MessageSquare, roles: ['Control Tower Team', 'Performance Managers Team', 'Administrateur'] },
]

export const Sidebar = () => {
  const { collapsed, setCollapsed, mobileOpen, setMobileOpen } = useSidebar()
  const isMobile = typeof window !== 'undefined' && window.innerWidth <= 768
  const { msgBadge, setMsgBadge, user, logout } = useAuthStore() 
  const [profileOpen, setProfileOpen] = useState(false)         // ← AJOUT
  const location = useLocation()

  // ← AJOUT — Badge WebSocket
 useEffect(() => {
  if (!user?.id) return  // ← vérifier user.id et pas juste user

  // Badge initial
  apiFetch('/messages/badge')
    .then(b => setMsgBadge(b.non_lus || 0))
    .catch(() => {})

  // WebSocket
  let ws = null
  let ping = null
  let reconnectTimeout = null

  const connect = () => {
    const token = localStorage.getItem('kpi_token')
    
    // ← Lire le user DIRECTEMENT depuis le store au moment de la connexion
    const currentUser = useAuthStore.getState().user
    
    if (!currentUser?.id) return  // sécurité
    
    console.log('Connecting WS for user:', currentUser.id)  // debug
    
    const WS_BASE = import.meta.env.VITE_WS_URL || 'wss://kpi-backend-latest.onrender.com'
ws = new WebSocket(
    `${WS_BASE}/api/messages/ws/${currentUser.id}?token=${token}`
)

    ws.onopen = () => {
      // Ping toutes les 30s pour garder la connexion vivante
      ping = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 30000)
    }

// Dans le useEffect, remplacer ws.onmessage :
   ws.onmessage = (event) => {
    try {
        const data = JSON.parse(event.data)
        if (data.type === 'badge') {
            setMsgBadge(data.non_lus || 0)
        }
        if (data.type === 'nouveau_message') {
            // Déclencher un événement custom pour que MessagesPage recharge
            window.dispatchEvent(new CustomEvent('nouveau_message'))
        }
        if (data.type === 'kpi_data_updated') {
            window.dispatchEvent(new CustomEvent('kpi_data_updated'))
        }
    } catch {}
}

    ws.onclose = () => {
      clearInterval(ping)
      // Reconnexion automatique après 3s si fermeture inattendue
      reconnectTimeout = setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      ws.close()
    }
  }

  connect()

  return () => {
    clearTimeout(reconnectTimeout)
    clearInterval(ping)
    if (ws) {
      ws.onclose = null  // ← empêcher la reconnexion au démontage
      ws.close()
    }
  }
}, [user?.id])  // ← dépendance sur user.id uniquement, pas tout user


  const navItems = NAV_ITEMS.filter(item =>
    user && item.roles.includes(user.role)
  )

  return (
    <>
    {mobileOpen && (
      <div className={styles.overlay} onClick={() => setMobileOpen(false)} />
    )}
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ''} ${mobileOpen ? styles.mobileOpen : ''}`}>
      {/* Logo */}
      <div className={styles.logo}>
        <div className={styles.logoIcon}>
          <Ship size={18} />
        </div>
        {!collapsed && (
          <div className={styles.logoText}>
            <span className={styles.logoName}>KPI Platform</span>
            <span className={styles.logoSub}>Maritime Logistics</span>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className={styles.nav}>
        {navItems.map((item) => {
          const Icon = item.icon
          const active = location.pathname.startsWith(item.path)
          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={`${styles.navItem} ${active ? styles.active : ''}`}
              title={collapsed ? item.label : undefined}
              onClick={() => setMobileOpen(false)}
            >
              <div className={styles.navIcon} style={{ position: 'relative' }}>
                <Icon size={16} />
                {active && <span className={styles.activeIndicator} />}
                {/* ← AJOUT badge Messages */}
                {item.path === '/messages' && msgBadge > 0 && (
                  <span style={{
                    position: 'absolute',
                    top: -6,
                    right: -6,
                    background: 'var(--color-danger)',
                    color: '#fff',
                    borderRadius: '50%',
                    fontSize: 9,
                    fontWeight: 700,
                    width: 15,
                    height: 15,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}>
                    {msgBadge > 9 ? '9+' : msgBadge}
                  </span>
                )}
              </div>
              {!collapsed && <span className={styles.navLabel}>{item.label}</span>}
            </NavLink>
          )
        })}
      </nav>

      {/* Footer */}
      <div className={styles.footer}>
        {user && (
          <div className={styles.userCardWrap}>
            <button
              className={styles.userCard}
              onClick={() => setProfileOpen(p => !p)}
              title="Paramètres / Déconnexion"
            >
              <div className={styles.avatar}>
                {user.prenom?.[0]}{user.nom?.[0]}
              </div>
              {!collapsed && (
                <div className={styles.userInfo}>
                  <span className={styles.userName}>{user.prenom} {user.nom}</span>
                  <span className={styles.userRole}>{user.role}</span>
                </div>
              )}
            </button>

            {/* Popup menu */}
            {profileOpen && (
              <div className={styles.profileMenu}>
                <NavLink to="/settings" className={styles.profileMenuItem} onClick={() => setProfileOpen(false)}>
                  <Settings size={13} />
                  Paramètres
                </NavLink>
                <button className={`${styles.profileMenuItem} ${styles.profileMenuDanger}`} onClick={logout}>
                  <LogOut size={13} />
                  Déconnexion
                </button>
              </div>
            )}
          </div>
        )}

        <button
          className={styles.collapseBtn}
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? 'Développer' : 'Réduire'}
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>
    </aside>
    </>
  )
}
