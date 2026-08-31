# KPI Monitoring Platform — Frontend

Frontend React premium pour la plateforme de monitoring KPI maritime.

## Stack

- **React 18** + Vite
- **Recharts** — graphiques (barres, lignes, radar, camembert)
- **Zustand** — gestion d'état (auth, user)
- **React Router v6** — navigation SPA
- **react-hot-toast** — notifications
- **lucide-react** — icônes
- **CSS Modules** — styles scopés par composant

## Lancer le développement

```bash
npm install
npm run dev
```

L'application tourne sur http://localhost:3000 et proxifie `/api` vers `http://localhost:8000`.

## Build production

```bash
npm run build
npm run preview
```

## Pages disponibles

| Route | Page | Rôles |
|-------|------|-------|
| `/login` | Connexion | Public |
| `/change-password` | Changement mdp | Authentifié |
| `/dashboard` | Dashboard KPI (5 cartes + graphiques) | CTT + PMT |
| `/shipments` | Gestion shipments (CRUD) | CTT + PMT |
| `/kpis` | Analyse détaillée par KPI | CTT + PMT |
| `/carriers` | Rapport performance carriers | CTT + PMT |
| `/prediction` | Prédiction ML retard | CTT + PMT |
| `/messages` | Messagerie interne | CTT + PMT |
| `/admin` | Administration comptes | Admin |

## Architecture

```
src/
├── components/
│   ├── ui/          # Button, Badge, Modal, Input, Table, Skeleton
│   ├── layout/      # AppLayout, Sidebar, Header
│   └── features/    # KPICard, FilterBar
├── pages/           # Une page par route
├── store/           # Zustand auth store + apiFetch helper
└── styles/          # globals.css (design tokens CSS)
```

## Design System

- **Palette** : dark navy (#0a0c10) + ocean blue (#3b82f6) + statuts sémantiques
- **Typographie** : Inter (UI) + JetBrains Mono (données)
- **Animations** : fadeIn staggeré, compteurs animés, transitions fluides
- **Composants** : glassmorphism léger, ombres profondes, hover lift

