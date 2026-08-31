import React, { useState, useEffect } from 'react'
import { AppLayout } from '../components/layout/AppLayout'
import { Header } from '../components/layout/Header'
import { DataTable } from '../components/ui/Table'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Modal, ConfirmModal } from '../components/ui/Modal'
import { Input, Select } from '../components/ui/Input'
import { SkeletonTable } from '../components/ui/Skeleton'
import { apiFetch } from '../store/auth'
import { UserPlus, Shield, Lock, ToggleLeft, ToggleRight, Key, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import styles from './AdminPage.module.css'

const ROLES = [
  { id: 1, label: 'Administrateur' },
  { id: 2, label: 'Control Tower Team' },
  { id: 3, label: 'Performance Managers Team' },
]

const statutVariant = (s) => {
  if (s === 'actif')   return 'success'
  if (s === 'inactif') return 'default'
  if (s === 'bloque')  return 'danger'
  return 'default'
}

export const AdminPage = () => {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [resetTarget, setResetTarget] = useState(null)
  const [toggleTarget, setToggleTarget] = useState(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [form, setForm] = useState({ nom: '', prenom: '', login: '', password: '', role: 'Control Tower Team' })
  const [resetPwd, setResetPwd] = useState('')

  const load = () => {
    setLoading(true)
    apiFetch('/admin/users')
      .then(setUsers)
      .catch(() => toast.error('Impossible de charger les utilisateurs'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    setActionLoading(true)
    try {
      await apiFetch('/admin/users', {
        method: 'POST',
        body: JSON.stringify(form),
      })
      toast.success(`Compte créé pour ${form.prenom} ${form.nom}`)
      setCreateOpen(false)
      setForm({ nom: '', prenom: '', login: '', password: '', role: 'Control Tower Team' })
      load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setActionLoading(false)
    }
  }

  const handleToggle = async () => {
    setActionLoading(true)
    try {
      await apiFetch(`/admin/users/${toggleTarget.id}/toggle`, { method: 'PUT' })
      toast.success(`Compte ${toggleTarget.statut === 'actif' ? 'désactivé' : 'réactivé'}`)
      setToggleTarget(null)
      load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setActionLoading(false)
    }
  }

  const handleUnlock = async (userId) => {
    try {
      await apiFetch(`/admin/users/${userId}/unlock`, { method: 'PUT' })
      toast.success('Compte déverrouillé')
      load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handleResetPwd = async () => {
    setActionLoading(true)
    try {
      await apiFetch(`/admin/users/${resetTarget.id}/reset-password`, {
        method: 'POST',
        body: JSON.stringify({ nouveau_password: resetPwd }),
      })
      toast.success('Mot de passe réinitialisé — l\'utilisateur devra le changer à la connexion')
      setResetTarget(null)
      setResetPwd('')
    } catch (e) {
      toast.error(e.message)
    } finally {
      setActionLoading(false)
    }
  }

  const columns = [
    {
      key: 'nom', label: 'Utilisateur',
      render: (_, row) => (
        <div className={styles.userCell}>
          <div className={styles.avatar}>{row.prenom?.[0]}{row.nom?.[0]}</div>
          <div>
            <p className={styles.userName}>{row.prenom} {row.nom}</p>
            <p className={styles.userLogin}>{row.login}</p>
          </div>
        </div>
      )
    },
    { key: 'nom_role', label: 'Rôle', render: (v) => <Badge variant="accent" size="sm">{v}</Badge> },
    {
      key: 'statut', label: 'Statut',
      render: (v) => <Badge variant={statutVariant(v)} dot size="sm">{v}</Badge>
    },
    {
      key: 'tentatives_echouees', label: 'Tentatives', align: 'center',
      render: (v) => (
        <span style={{ color: v >= 3 ? 'var(--color-danger)' : 'var(--color-text-secondary)', fontVariantNumeric: 'tabular-nums' }}>
          {v}
        </span>
      )
    },
    {
      key: 'doit_changer_mdp', label: 'Mdp temp.', align: 'center',
      render: (v) => v ? <Badge variant="warning" size="sm">À changer</Badge> : <span style={{ color: 'var(--color-text-tertiary)', fontSize: '11px' }}>—</span>
    },
    {
      key: 'actions', label: '',
      render: (_, row) => (
        <div className={styles.actions}>
          {row.statut === 'bloque' && (
            <button className={styles.iconBtn} title="Déverrouiller" onClick={() => handleUnlock(row.id)}>
              <Lock size={12} />
            </button>
          )}
          <button
            className={`${styles.iconBtn} ${row.statut === 'actif' ? styles.danger : ''}`}
            title={row.statut === 'actif' ? 'Désactiver' : 'Réactiver'}
            onClick={() => setToggleTarget(row)}
          >
            {row.statut === 'actif' ? <ToggleRight size={13} /> : <ToggleLeft size={13} />}
          </button>
          <button className={styles.iconBtn} title="Réinitialiser mdp" onClick={() => setResetTarget(row)}>
            <Key size={12} />
          </button>
        </div>
      )
    },
  ]

  // Stats
  const actifs = users.filter(u => u.statut === 'actif').length
  const bloques = users.filter(u => u.statut === 'bloque').length

  return (
    <AppLayout>
      <Header title="Administration" subtitle="Gestion des comptes utilisateurs">
        <button className={styles.refreshBtn} onClick={load}><RefreshCw size={13} /></button>
        <Button size="sm" icon={UserPlus} onClick={() => setCreateOpen(true)}>Créer un compte</Button>
      </Header>

      <div className={styles.content}>
        {/* Stats */}
        <div className={styles.stats}>
          {[
            { label: 'Utilisateurs actifs', value: actifs, color: 'var(--color-success)' },
            { label: 'Comptes bloqués', value: bloques, color: 'var(--color-danger)' },
            { label: 'Total comptes', value: users.length, color: 'var(--color-text-secondary)' },
          ].map(({ label, value, color }) => (
            <div key={label} className={styles.statCard}>
              <span className={styles.statVal} style={{ color }}>{value}</span>
              <span className={styles.statLabel}>{label}</span>
            </div>
          ))}
        </div>

        {loading ? <SkeletonTable rows={5} cols={6} /> : (
          <DataTable columns={columns} data={users} rowKey="id" emptyMessage="Aucun utilisateur" />
        )}
      </div>

      {/* Create user modal */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Créer un compte"
        size="sm"
        footer={
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <Button variant="ghost" size="sm" onClick={() => setCreateOpen(false)}>Annuler</Button>
            <Button size="sm" icon={UserPlus} onClick={handleCreate} loading={actionLoading}>Créer</Button>
          </div>
        }
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <Input label="Prénom" value={form.prenom} onChange={e => setForm({ ...form, prenom: e.target.value })} required />
            <Input label="Nom" value={form.nom} onChange={e => setForm({ ...form, nom: e.target.value })} required />
          </div>
          <Input label="Identifiant (login)" value={form.login} onChange={e => setForm({ ...form, login: e.target.value })} required />
          <Input label="Mot de passe temporaire" type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} required />
          <Select label="Rôle" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>
            {ROLES.map(r => <option key={r.id} value={r.label}>{r.label}</option>)}
          </Select>
        </div>
      </Modal>

      {/* Toggle confirm */}
      <ConfirmModal
        open={!!toggleTarget}
        onClose={() => setToggleTarget(null)}
        onConfirm={handleToggle}
        title={toggleTarget?.statut === 'actif' ? 'Désactiver le compte' : 'Réactiver le compte'}
        message={`Confirmer ${toggleTarget?.statut === 'actif' ? 'la désactivation' : 'la réactivation'} du compte de ${toggleTarget?.prenom} ${toggleTarget?.nom} ?`}
        confirmLabel={toggleTarget?.statut === 'actif' ? 'Désactiver' : 'Réactiver'}
        danger={toggleTarget?.statut === 'actif'}
        loading={actionLoading}
      />

      {/* Reset password modal */}
      <Modal
        open={!!resetTarget}
        onClose={() => { setResetTarget(null); setResetPwd('') }}
        title={`Réinitialiser le mdp — ${resetTarget?.prenom} ${resetTarget?.nom}`}
        size="sm"
        footer={
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <Button variant="ghost" size="sm" onClick={() => setResetTarget(null)}>Annuler</Button>
            <Button size="sm" icon={Key} onClick={handleResetPwd} loading={actionLoading}>Réinitialiser</Button>
          </div>
        }
      >
        <Input
          label="Nouveau mot de passe temporaire"
          type="password"
          value={resetPwd}
          onChange={e => setResetPwd(e.target.value)}
          hint="L'utilisateur devra le changer à sa prochaine connexion."
        />
      </Modal>
    </AppLayout>
  )
}
