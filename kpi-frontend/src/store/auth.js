import { create } from 'zustand'

const API_BASE = '/api'

export const useAuthStore = create((set, get) => ({
  user:        null,
  token:       localStorage.getItem('kpi_token'),
  isLoading:   false,
  error:       null,

  // ✅ Présence — intégré directement ici
  presenceMap: {}, // { [user_id]: true/false }

  setUserPresence: (userId, enLigne) =>
    set(state => ({
      presenceMap: { ...state.presenceMap, [userId]: enLigne }
    })),

  setPresenceSnapshot: (userIds) =>
    set(state => {
      const map = { ...state.presenceMap }
      userIds.forEach(id => { map[id] = true })
      return { presenceMap: map }
    }),

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
      set({
        token: data.access_token,
        user: {
          id:               data.id,
          nom:              data.nom,
          prenom:           data.prenom,
          role:             data.role,
          doit_changer_mdp: data.doit_changer_mdp,
        },
        isLoading: false,
      })
      return data
    } catch (e) {
      set({ error: e.message, isLoading: false })
      throw e
    }
  },

  logout: () => {
    localStorage.removeItem('kpi_token')
    set({ user: null, token: null, presenceMap: {} }) // ✅ reset présence au logout
  },

  setUser: (user) => set({ user }),
}))

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
    localStorage.removeItem('kpi_token')
    window.location.href = '/login'
    throw new Error('Session expirée')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Erreur ${res.status}`)
  }
  const text = await res.text()
  return text ? JSON.parse(text) : {}
}