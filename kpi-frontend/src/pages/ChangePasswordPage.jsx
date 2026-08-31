import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Lock, Eye, EyeOff, Shield } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { apiFetch, useAuthStore } from '../store/auth'
import toast from 'react-hot-toast'
import styles from './LoginPage.module.css'

export const ChangePasswordPage = () => {
  const navigate = useNavigate()
  const { user, setUser } = useAuthStore()
  const [form, setForm] = useState({ ancien_password: '', nouveau_password: '', confirm: '' })
  const [loading, setLoading] = useState(false)
  const [show, setShow] = useState({ old: false, new: false, confirm: false })

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
    setLoading(true)
    try {
      await apiFetch('/admin/change-password', {
        method: 'POST',
        body: JSON.stringify({ ancien_password: form.ancien_password, nouveau_password: form.nouveau_password }),
      })
      toast.success('Mot de passe modifié avec succès')
      if (user) {
        setUser({ ...user, doit_changer_mdp: false })
      }
      navigate('/dashboard')
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.bg}>
        <div className={styles.bgOrb1} />
        <div className={styles.bgOrb2} />
        <div className={styles.grid} />
      </div>

      <div className={styles.card}>
        <div className={styles.logo}>
          <div className={styles.logoIcon} style={{ background: 'linear-gradient(135deg, #7c3aed, #a855f7)' }}>
            <Shield size={20} />
          </div>
          <div>
            <h1 className={styles.logoName}>Sécurité du compte</h1>
            <p className={styles.logoSub}>Modification du mot de passe</p>
          </div>
        </div>

        {user?.doit_changer_mdp && (
          <div style={{ background: 'var(--color-warning-dim)', border: '1px solid rgba(245,158,11,0.2)', borderRadius: 'var(--radius-md)', padding: '10px 14px', marginBottom: 8, fontSize: 12, color: 'var(--color-warning)' }}>
            ⚠️ Vous devez définir un nouveau mot de passe avant de continuer.
          </div>
        )}

        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.formHeader}>
            <h2 className={styles.formTitle}>Nouveau mot de passe</h2>
          </div>

          {[
            { key: 'ancien_password', label: 'Mot de passe actuel', showKey: 'old' },
            { key: 'nouveau_password', label: 'Nouveau mot de passe', showKey: 'new' },
            { key: 'confirm', label: 'Confirmer le nouveau mot de passe', showKey: 'confirm' },
          ].map(({ key, label, showKey }) => (
            <div key={key} className={styles.field}>
              <label className={styles.label}>{label}</label>
              <div className={styles.inputWrap}>
                <Lock size={14} className={styles.inputIcon} />
                <input
                  type={show[showKey] ? 'text' : 'password'}
                  className={styles.input}
                  placeholder="••••••••"
                  value={form[key]}
                  onChange={e => setForm({ ...form, [key]: e.target.value })}
                  required
                />
                <button type="button" className={styles.eyeBtn} onClick={() => setShow(s => ({ ...s, [showKey]: !s[showKey] }))}>
                  {show[showKey] ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>
          ))}

          <Button type="submit" fullWidth size="lg" loading={loading} icon={Lock} iconPosition="left">
            Mettre à jour
          </Button>

        </form>
      </div>
    </div>
  )
}
