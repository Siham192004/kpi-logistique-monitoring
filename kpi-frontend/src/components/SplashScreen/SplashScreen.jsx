import React, { useEffect, useState } from 'react'
import styles from './SplashScreen.module.css'

export const SplashScreen = ({ onDone }) => {
  const [phase, setPhase] = useState('enter')

  useEffect(() => {
    const holdTimer = setTimeout(() => setPhase('exit'), 5500)
    const doneTimer = setTimeout(() => onDone(), 6500)
    return () => { clearTimeout(holdTimer); clearTimeout(doneTimer) }
  }, [onDone])

  return (
    <div className={`${styles.splash} ${phase === 'exit' ? styles.exit : ''}`}>

      <div className={styles.bg} />
      <div className={styles.overlay} />

      <div className={styles.content}>

        {/* Logo */}
        <div className={styles.logoWrap}>
          <svg className={styles.logoSvg} viewBox="0 0 56 56" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M8 34 L28 40 L48 34 L44 44 Q28 50 12 44 Z" fill="url(#shipGrad)" opacity="0.95"/>
            <rect x="20" y="22" width="16" height="13" rx="2" fill="url(#shipGrad)" opacity="0.85"/>
            <path d="M10 34 L46 34" stroke="white" strokeWidth="1.5" opacity="0.4"/>
            <rect x="24" y="14" width="8" height="10" rx="1.5" fill="url(#shipGrad)"/>
            <circle cx="28" cy="11" r="2" fill="white" opacity="0.25"/>
            <path d="M4 42 Q14 39 24 42 Q34 45 44 42 Q50 40 52 42" stroke="white" strokeWidth="1.5" strokeLinecap="round" opacity="0.35" fill="none"/>
            <defs>
              <linearGradient id="shipGrad" x1="8" y1="14" x2="48" y2="50" gradientUnits="userSpaceOnUse">
                <stop offset="0%" stopColor="#60a5fa"/>
                <stop offset="100%" stopColor="#1d4ed8"/>
              </linearGradient>
            </defs>
          </svg>
        </div>

        {/* Name */}
        <div className={styles.appName}>
          <span className={styles.appNameKpi}>KPI</span>
          <span className={styles.appNamePlatform}>Platform</span>
        </div>
        <p className={styles.tagline}>Maritime Logistics Intelligence</p>

        {/* Ship animation */}
        <div className={styles.shipTrack}>
          <div className={styles.wake} />
          <svg className={styles.ship} width="48" height="22" viewBox="0 0 48 22" fill="none">
            {/* hull */}
            <path d="M2 14 L6 20 L42 20 L46 14 Z" fill="url(#hullG)" opacity="0.95"/>
            {/* superstructure */}
            <rect x="14" y="7" width="14" height="8" rx="1.5" fill="url(#hullG)" opacity="0.9"/>
            {/* bridge */}
            <rect x="17" y="3" width="8" height="5" rx="1" fill="url(#hullG)"/>
            {/* mast */}
            <line x1="21" y1="1" x2="21" y2="7" stroke="rgba(255,255,255,0.5)" strokeWidth="1"/>
            {/* waterline */}
            <path d="M2 17 L46 17" stroke="rgba(255,255,255,0.2)" strokeWidth="0.8"/>
            <defs>
              <linearGradient id="hullG" x1="2" y1="3" x2="46" y2="20" gradientUnits="userSpaceOnUse">
                <stop offset="0%" stopColor="#93c5fd"/>
                <stop offset="100%" stopColor="#1e40af"/>
              </linearGradient>
            </defs>
          </svg>
        </div>

      </div>
    </div>
  )
}

