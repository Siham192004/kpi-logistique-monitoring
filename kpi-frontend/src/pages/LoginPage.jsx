import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Ship, Eye, EyeOff, Lock, User, ArrowRight } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import { Button } from '../components/ui/Button'
import toast from 'react-hot-toast'
import styles from './LoginPage.module.css'

export const LoginPage = () => {
  const [form, setForm] = useState({ login: '', password: '' })
  const [showPass, setShowPass] = useState(false)
  const { login, isLoading } = useAuthStore()
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      const data = await login(form.login, form.password)
      if (data.doit_changer_mdp) {
        navigate('/change-password')
      } else {
        toast.success(`Bienvenue, ${data.prenom} !`)
        navigate('/dashboard')
      }
    } catch (err) {
      toast.error(err.message || 'Identifiants incorrects')
    }
  }

  return (
    <div className={styles.page}>
      {/* Animated background */}
      <div className={styles.bg}>
        <div className={styles.bgOrb1} />
        <div className={styles.bgOrb2} />
        <div className={styles.grid} />
      </div>

      {/* Card */}
      <div className={styles.card}>
        {/* Logo */}
        <div className={styles.logo}>
          <div className={styles.logoIcon}>
            <Ship size={24} />
          </div>
          <div>
            <h1 className={styles.logoName}>KPI Platform</h1>
            <p className={styles.logoSub}>Maritime Logistics</p>
          </div>
        </div>

        {/* Form */}
        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.formHeader}>
            <h2 className={styles.formTitle}>Connexion</h2>
            <p className={styles.formSub}>Accédez à votre espace de suivi</p>
          </div>

          <div className={styles.field}>
            <label className={styles.label}>Identifiant</label>
            <div className={styles.inputWrap}>
              <User size={14} className={styles.inputIcon} />
              <input
                type="text"
                className={styles.input}
                placeholder="Votre identifiant"
                value={form.login}
                onChange={(e) => setForm({ ...form, login: e.target.value })}
                autoComplete="username"
                required
              />
            </div>
          </div>

          <div className={styles.field}>
            <label className={styles.label}>Mot de passe</label>
            <div className={styles.inputWrap}>
              <Lock size={14} className={styles.inputIcon} />
              <input
                type={showPass ? 'text' : 'password'}
                className={styles.input}
                placeholder="••••••••"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                autoComplete="current-password"
                required
              />
              <button
                type="button"
                className={styles.eyeBtn}
                onClick={() => setShowPass(!showPass)}
                tabIndex={-1}
              >
                {showPass ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          <Button
            type="submit"
            fullWidth
            size="lg"
            loading={isLoading}
            icon={ArrowRight}
            iconPosition="right"
          >
            Se connecter
          </Button>
        </form>

        <p className={styles.footer}>
          En cas de problème d'accès, contactez votre administrateur système.
        </p>
      </div>
    </div>
  )
}
