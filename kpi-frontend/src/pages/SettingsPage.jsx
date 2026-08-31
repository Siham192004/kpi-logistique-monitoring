import React, { useState } from 'react'
import { AppLayout } from '../components/layout/AppLayout'
import { Header } from '../components/layout/Header'
import { Lock, Eye, EyeOff, CheckCircle } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { apiFetch, useAuthStore } from '../store/auth'
import toast from 'react-hot-toast'
import styles from './SettingsPage.module.css'

export const SettingsPage = () => {
  const { user, setUser } = useAuthStore()
  const [form, setForm] = useState({ ancien_password: '', nouveau_password: '', confirm: '' })
  const [loading, setLoading] = useState(false)
  const [show, setShow] = useState({ old: false, new: false, confirm: false })
  const [success, setSuccess] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (form.nouveau_password !== form.confirm) {
      toast.error('Les mots de passe ne correspondent pas')
      return
    }
    if (form.nouveau_password.length < 6) {
      toast.error('Le mot de passe doit contenir au moins 6 caractères')
      return
    }
    if (form.ancien_password === form.nouveau_password) {
      toast.error("Le nouveau mot de passe doit être différent de l'ancien")
      return
    }
    setLoading(true)
    try {
      await apiFetch('/admin/change-password', {
        method: 'POST',
        body: JSON.stringify({
          ancien_password: form.ancien_password,
          nouveau_password: form.nouveau_password,
        }),
      })
      toast.success('Mot de passe modifié avec succès')
      if (user) setUser({ ...user, doit_changer_mdp: false })
      setForm({ ancien_password: '', nouveau_password: '', confirm: '' })
      setSuccess(true)
      setTimeout(() => setSuccess(false), 4000)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  const fields = [
    { key: 'ancien_password',  label: 'Mot de passe actuel',              showKey: 'old'     },
    { key: 'nouveau_password', label: 'Nouveau mot de passe',             showKey: 'new'     },
    { key: 'confirm',          label: 'Confirmer le nouveau mot de passe', showKey: 'confirm' },
  ]

  return (
    <AppLayout>
      <Header title="Paramètres" subtitle="Gestion de votre compte" />
      <div className={styles.page}>

        {/* Infos compte */}
        <div className={styles.card}>
          <h3 className={styles.cardTitle}>Mon compte</h3>
          <div className={styles.infoGrid}>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>Nom complet</span>
              <span className={styles.infoValue}>{user?.prenom} {user?.nom}</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>Rôle</span>
              <span className={styles.infoValue}>{user?.role}</span>
            </div>
          </div>
        </div>

        {/* Changement mot de passe */}
        <div className={styles.card}>
          <h3 className={styles.cardTitle}>
            <Lock size={15} style={{ marginRight: 8, verticalAlign: 'middle' }} />
            Changer le mot de passe
          </h3>

          {success && (
            <div className={styles.successBanner}>
              <CheckCircle size={15} />
              Mot de passe modifié avec succès.
            </div>
          )}

          <form onSubmit={handleSubmit} className={styles.form}>
            {fields.map(({ key, label, showKey }) => (
              <div key={key} className={styles.field}>
                <label className={styles.label}>{label}</label>
                <div className={styles.inputWrap}>
                  <input
                    type={show[showKey] ? 'text' : 'password'}
                    className={styles.input}
                    placeholder="••••••••"
                    value={form[key]}
                    onChange={e => setForm({ ...form, [key]: e.target.value })}
                    required
                  />
                  <button type="button" className={styles.eyeBtn}
                    onClick={() => setShow(s => ({ ...s, [showKey]: !s[showKey] }))}>
                    {show[showKey] ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>
            ))}
            <div className={styles.formFooter}>
              <Button type="submit" loading={loading} icon={Lock} iconPosition="left" size="sm">
                Mettre à jour
              </Button>
            </div>
          </form>
        </div>

      </div>
    </AppLayout>
  )
}