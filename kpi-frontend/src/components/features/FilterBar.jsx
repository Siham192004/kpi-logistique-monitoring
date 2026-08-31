import React from 'react'
import { Filter, X, RefreshCw } from 'lucide-react'
import { Select } from '../ui/Input'
import { Button } from '../ui/Button'
import styles from './FilterBar.module.css'

export const FilterBar = ({ filters, onChange, filtres, loading, onRefresh }) => {
  const hasActiveFilters = filters.mois || filters.carrier 

  const handleChange = (key, value) => {
    onChange({ ...filters, [key]: value || null })
  }

  const handleReset = () => {
    onChange({ mois: null, carrier: null})
  }

  return (
    <div className={styles.bar}>
      <div className={styles.left}>
        <div className={styles.filterIcon}>
          <Filter size={13} />
        </div>
        <span className={styles.filterLabel}>Filtres</span>

        <div className={styles.selects}>
          <Select
            value={filters.mois || ''}
            onChange={(e) => handleChange('mois', e.target.value)}
            style={{ width: 140 }}
          >
            <option value="">Tous les mois</option>
            {(filtres?.mois || []).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </Select>

          <Select
            value={filters.carrier || ''}
            onChange={(e) => handleChange('carrier', e.target.value)}
            style={{ width: 180 }}
          >
            <option value="">Tous les carriers</option>
            {(filtres?.carriers || []).map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </Select>
        </div>

        {hasActiveFilters && (
          <button className={styles.resetBtn} onClick={handleReset}>
            <X size={12} />
            Réinitialiser
          </button>
        )}
      </div>

      <button
        className={`${styles.refreshBtn} ${loading ? styles.spinning : ''}`}
        onClick={onRefresh}
        title="Actualiser"
      >
        <RefreshCw size={13} />
      </button>
    </div>
  )
}
