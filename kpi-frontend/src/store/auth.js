import { create } from 'zustand'

const API_BASE = '/api'

// ── WebSocket manager (singleton) ──────────────────────────────────────────
let wsInstance      = null
let wsReconnectTimer = null
let wsDelay         = 1000   // backoff initial
const WS_MAX_DELAY  = 30000  // 30s max

const clearReconnectTimer = () => {
  if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null }
}

const connectWS = (userId) => {
  // 1. Toujours lire le token FRAIS au moment de la connexion
  const token = localStorage.getItem('kpi_token')
  if (!token || !userId) return

  // 2. Fermer proprement l'ancienne instance
  if (wsInstance) {
    wsInstance._manualClose = true   // flag pour ne pas déclencher la reconnexion
    wsInstance.close()
    wsInstance = null
  }
  clearReconnectTimer()

  const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${protocol}://${location.host}/api/messages/ws/${userId}?token=${token}`)
  wsInstance = ws

  ws.onopen = () => {
    wsDelay = 1000  // reset backoff on success
    console.log('[WS] Connecté')
  }

  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data.type === 'nouveau_message') {
        window.dispatchEvent(new CustomEvent('nouveau_message', { detail: data }))
        // Incrémenter le badge via le store
        useAuthStore.getState().setMsgBadge(
          useAuthStore.getState().msgBadge + 1
        )
      }
      if (data.type === 'badge') {
        useAuthStore.getState().setMsgBadge(data.count ?? 0)
      }
    } catch {}
  }

  ws.onerror = (err) => {
    console.warn('[WS] Erreur', err)
  }

  ws.onclose = (e) => {
    wsInstance = null
    // 3. Ne pas reconnecter si : fermeture manuelle, token invalide (403), ou déconnecté
    if (ws._manualClose) return
    if (e.code === 4003 || e.code === 1008) return  // forbidden / policy violation

    const currentToken = localStorage.getItem('kpi_token')
    const currentUser  = useAuthStore.getState().user
    if (!currentToken || !currentUser) return  // déconnecté → pas de reconnexion

    // 4. Backoff exponentiel
    console.log(`[WS] Reconnexion dans ${wsDelay}ms…`)
    wsReconnectTimer = setTimeout(() => {
      wsDelay = Math.min(wsDelay * 2, WS_MAX_DELAY)
      connectWS(currentUser.id)
    }, wsDelay)
  }
}

const disconnectWS = () => {
  clearReconnectTimer()
  if (wsInstance) {
    wsInstance._manualClose = true
    wsInstance.close()
    wsInstance = null
  }
  wsDelay = 1000
}

// ── Store ──────────────────────────────────────────────────────────────────
export const useAuthStore = create((set, get) => ({
  user:      null,
  token:     localStorage.getItem('kpi_token'),
  isLoading: false,
  error:     null,
  msgBadge:  0,

  setMsgBadge: (n) => set({ msgBadge: n }),

  login: async (login, password) => {
    set({ isLoading: true, error: null })
    try {
      const res = await fetch(`${API_BASE}/admin/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login, password }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Identifiants incorrects')
      }
      const data = await res.json()
      localStorage.setItem('kpi_token', data.access_token)

      const user = {
        id:               data.id,
        nom:              data.nom,
        prenom:           data.prenom,
        role:             data.role,
        doit_changer_mdp: data.doit_changer_mdp,
      }

      set({ token: data.access_token, user, isLoading: false })

      // ✅ Lancer le WS avec le NOUVEAU token, après que le store soit à jour
      connectWS(user.id)

      return data
    } catch (e) {
      set({ error: e.message, isLoading: false })
      throw e
    }
  },

  logout: () => {
    disconnectWS()   // ✅ Couper le WS proprement avant de vider le token
    localStorage.removeItem('kpi_token')
    set({ user: null, token: null, msgBadge: 0 })
  },

  setUser: (user) => set({ user }),

  // ✅ À appeler au démarrage de l'app si l'user est déjà loggé (refresh de page)
  initWS: (userId) => {
  const id = userId ?? get().user?.id   // ← accepte un id explicite ou lit le store
  if (id) connectWS(id)
},
}))

// ── apiFetch (inchangé) ────────────────────────────────────────────────────
export const apiFetch = async (path, options = {}) => {
  const token = localStorage.getItem('kpi_token')
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (res.status === 401) {
    disconnectWS()   // ✅ Couper le WS si la session expire
    localStorage.removeItem('kpi_token')
    window.location.href = '/login'
    throw new Error('Session expirée')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    if (Array.isArray(err.detail)) {
      throw new Error(err.detail.map(e => e.msg).join('\n'))
    }
    throw new Error(err.detail || `Erreur ${res.status}`)
  }
  return res.json()
}