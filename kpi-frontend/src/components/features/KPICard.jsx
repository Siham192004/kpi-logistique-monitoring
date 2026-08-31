import React, { useEffect, useRef, useState } from 'react'
import { TrendingUp, TrendingDown, Minus, Activity } from 'lucide-react'
import { Badge, niveauToBadge, niveauLabel } from '../ui/Badge'
import styles from './KPICard.module.css'

/** Animated counter that counts up from 0 to target value */
const AnimatedValue = ({ value, suffix = '' }) => {
  const [display, setDisplay] = useState(0)
  const rafRef = useRef(null)

  useEffect(() => {
    if (value == null) return
    const start = performance.now()
    const duration = 1000
    const from = 0

    const tick = (now) => {
      const elapsed = now - start
      const progress = Math.min(elapsed / duration, 1)
      // easeOutExpo
      const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress)
      setDisplay(from + (value - from) * eased)
      if (progress < 1) rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [value])

  if (value == null) return <span>—</span>
  return <span>{display.toFixed(1)}{suffix}</span>
}

const KPI_META = {
  KPI1: {
    label: 'Volume chargé / alloué',
    description: 'Taux de réalisation des volumes de chargement',
    icon: '📦',
    color: 'accent',
    suffix: '%',
  },
  KPI2: {
    label: 'Volume alloué / réservé',
    description: 'Taux utilisation des réservations',
    icon: '📋',
    color: 'accent',
    suffix: '%',
  },
  KPI3: {
    label: 'Retards transbordement',
    description: 'Shipments critiques dans les ports de transit',
    icon: '⚓',
    color: 'warning',
    suffix: '',
  },
  KPI4: {
    label: 'Modifications & annulations',
    description: "Taux de modifications et d'annulations",
    icon: '✏️',
    color: 'danger',
    suffix: '%',
  },
  KPI5: {
    label: 'Déviation ETA vs ATA',
    description: "Ponctualité à l'arrivée",
    icon: '🕐',
    color: 'warning',
    suffix: '%',
  },
}

export const KPICard = ({ kpiId, data, index = 0, onClick }) => {
  const meta = KPI_META[kpiId] || {}
  const badgeVariant = niveauToBadge(data?.niveau)
  const isClickable = !!onClick

  return (
    <div
      className={`${styles.card} ${isClickable ? styles.clickable : ''}`}
      style={{ animationDelay: `${index * 70}ms` }}
      onClick={onClick}
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onKeyDown={isClickable ? (e) => e.key === 'Enter' && onClick() : undefined}
    >
      {/* Top bar glow */}
      <div className={`${styles.topGlow} ${styles[`glow_${badgeVariant.replace('-', '_')}`]}`} />

      {/* Header */}
      <div className={styles.header}>
        <div>
          <span className={styles.kpiId}>{kpiId}</span>
          <p className={styles.label}>{meta.label}</p>
        </div>
        <div className={styles.iconWrap}>
          <span className={styles.icon}>{meta.icon}</span>
        </div>
      </div>

      {/* Value */}
      <div className={styles.valueRow}>
        <span className={styles.value}>
          {data ? (
            kpiId === 'KPI3'
              ? data.valeur_affichee
              : <AnimatedValue value={data.valeur} suffix={meta.suffix} />
          ) : '—'}
        </span>
      </div>

      {/* Objective */}
      {data?.objectif_texte && (
        <p className={styles.objective}>
          <span className={styles.objectiveLabel}>Objectif</span>
          {data.objectif_texte}
        </p>
      )}

      {/* Footer */}
      <div className={styles.footer}>
        <Badge variant={badgeVariant} dot size="sm">
          {niveauLabel(data?.niveau)}
        </Badge>
        {data?.effectif != null && (
          <span className={styles.effectif}>
            {data.effectif.toLocaleString('fr-FR')} shipments
          </span>
        )}
      </div>
    </div>
  )
}
