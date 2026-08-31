import React, { useState, useEffect, useRef } from 'react'
import { AppLayout } from '../components/layout/AppLayout'
import { Header } from '../components/layout/Header'
import { DataTable } from '../components/ui/Table'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { SkeletonTable } from '../components/ui/Skeleton'
import { apiFetch } from '../store/auth'
import { Brain, AlertTriangle, CheckCircle, X } from 'lucide-react'
import toast from 'react-hot-toast'
import styles from './PredictionPage.module.css'

const RISK_COLORS = {
  Faible: { variant: 'success', color: 'var(--color-success)', barColor: 'var(--color-success)' },
  Modéré: { variant: 'warning', color: 'var(--color-warning)', barColor: 'var(--color-warning)' },
  Élevé:  { variant: 'critical', color: 'var(--color-danger)',  barColor: 'var(--color-danger)'  },
}

const ProbabilityBar = ({ value, niveau }) => {
  const barColor = RISK_COLORS[niveau]?.barColor || 'var(--color-success)'
  return (
    <div className={styles.probBar}>
      <div className={styles.probFill} style={{ width: `${value}%`, background: barColor }} />
    </div>
  )
}

export const PredictionPage = () => {
  const [eligibles, setEligibles]   = useState([])
  const [loading, setLoading]       = useState(true)
  const [predicting, setPredicting] = useState(false)
  const [selectedId, setSelectedId] = useState(null)
  const [result, setResult]         = useState(null)
  const contentRef                  = useRef(null)

  useEffect(() => {
    apiFetch('/predict/eligibles')
      .then(setEligibles)
      .catch(() => toast.error('Impossible de charger les shipments éligibles'))
      .finally(() => setLoading(false))
  }, [])

  const handlePredict = async (shipmentId) => {
    setSelectedId(shipmentId)
    setPredicting(true)
    setResult(null)
    try {
      const res = await apiFetch('/predict/', {
        method: 'POST',
        body: JSON.stringify({ shipment_id: shipmentId }),
      })
      setResult(res)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setPredicting(false)
    }
  }

  const handleClose = () => {
    setResult(null)
    setSelectedId(null)
  }

  const showPanel = result || predicting
  const riskStyle = result ? RISK_COLORS[result.niveau_risque] || RISK_COLORS.Moyen : null

  const columns = [
    { key: 'id', label: '#', render: v => <span className={styles.monoId}>#{v}</span> },
    { key: 'carrier', label: 'Carrier', sortable: true, render: v => <span className={styles.carrierCell}>{v || '—'}</span> },
    { key: 'vessel_nom', label: 'Navire' },
    { key: 'port_chargement', label: 'Départ', sortable: true },
    { key: 'port_dechargement', label: 'Arrivée', sortable: true },
    { key: 'etd', label: 'ETD', render: v => v ? new Date(v).toLocaleDateString('fr-FR') : '—' },
    { key: 'eta', label: 'ETA', render: v => v ? new Date(v).toLocaleDateString('fr-FR') : '—' },
    { key: 'transit_time', label: 'Transit', align: 'right', render: v => v ? `${v} j` : '—' },
    {
      key: 'actions', label: '',
      render: (_, row) => (
        <Button
          size="sm"
          variant={selectedId === row.id ? 'primary' : 'secondary'}
          icon={Brain}
          onClick={() => handlePredict(row.id)}
          loading={predicting && selectedId === row.id}
        >
          Prédire
        </Button>
      )
    }
  ]

  return (
    <AppLayout>
      <Header
        title="Prédiction ML"
        subtitle="Modèle de régression logistique — risque de retard"
      />

      <div className={styles.content} ref={contentRef}>

        <div className={styles.infoBanner}>
          <Brain size={15} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
          <p className={styles.infoText}>
            Le modèle analyse les features du shipment (carrier, ports, volumes, transit time, saison)
            pour prédire la probabilité de retard à l'arrivée. Sélectionnez un shipment et cliquez
            sur <strong>Prédire</strong>.
          </p>
        </div>

        <div className={`${styles.layout} ${showPanel ? styles.withResult : ''}`}>

          {/* LEFT — table */}
          <div className={styles.tableSection}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Shipments éligibles</h2>
              <Badge variant="accent" size="sm">{eligibles.length}</Badge>
            </div>
            {loading
              ? <SkeletonTable rows={6} cols={8} />
              : (
                <DataTable
                  columns={columns}
                  data={eligibles}
                  rowKey="id"
                  emptyMessage="Aucun shipment éligible à la prédiction"
                />
              )
            }
          </div>

          {/* RIGHT — result panel */}
          <div className={styles.resultPanel}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Résultat</h2>
              <button className={styles.closeBtn} onClick={handleClose} title="Fermer">
                <X size={13} />
              </button>
            </div>

            {predicting && (
              <div className={styles.stateBox}>
                <div className={styles.stateIcon} style={{ background: 'var(--color-accent-dim)' }}>
                  <Brain size={22} style={{ color: 'var(--color-accent)', animation: 'pulse 1.2s ease-in-out infinite' }} />
                </div>
                <p className={styles.stateTitle}>Analyse en cours…</p>
                <p className={styles.stateSub}>Le modèle calcule la prédiction</p>
              </div>
            )}

            {result && !predicting && (
              <div className={styles.resultCard} style={{ '--risk-color': riskStyle?.color }}>

                {/* Verdict */}
                <div className={styles.verdict}>
  <div
    className={styles.verdictIcon}
    style={{ background: riskStyle?.color + '22' }}
  >
    {result.niveau_risque === 'Élevé'
      ? <AlertTriangle size={26} color={riskStyle?.color} />
      : <CheckCircle size={26} color={riskStyle?.color} />
    }
  </div>
  <div>
    <p className={styles.verdictLabel}>{result.niveau_risque} risque</p>
    <Badge variant={riskStyle?.variant} dot>
      {result.probabilite_retard?.toFixed(1)}% de probabilité
    </Badge>
  </div>
</div>

                {/* Probability */}
                <div className={styles.probSection}>
                  <div className={styles.probHeader}>
                    <span className={styles.probLabel}>Probabilité de retard</span>
                    <span className={styles.probPercent} style={{ color: riskStyle?.color }}>
                      {result.probabilite_retard?.toFixed(1)}%
                    </span>
                  </div>
                  <ProbabilityBar value={result.probabilite_retard} niveau={result.niveau_risque} />
                </div>

                {/* Only NEW info not already in the table */}
                <div className={styles.context}>
                  <p className={styles.contextTitle}>Infos complémentaires</p>
                  <div className={styles.contextGrid}>
                   <div className={styles.contextItem}>
                   <span className={styles.contextLabel}>Vol. réservé</span>
                   <span className={styles.contextValue}>
                   {result.volume_booked ? `${result.volume_booked} m³` : '—'}
                   </span>
                  </div>
                  <div className={styles.contextItem}>
                    <span className={styles.contextLabel}>Shipment #</span>
                    <span className={styles.contextValue}>#{selectedId}</span>
                  </div>
                </div>

            {/* ✅ AJOUTER — Données météo */}
  {result.meteo && (
    <>
      <p className={styles.contextTitle} style={{ marginTop: '12px' }}>
        🌤️ Météo au départ / arrivée
      </p>
      <div className={styles.contextGrid}>
        <div className={styles.contextItem}>
          <span className={styles.contextLabel}>🌧️ Pluie ETD</span>
          <span className={styles.contextValue}>
            {result.meteo.etd_precipitation_mm != null
              ? `${result.meteo.etd_precipitation_mm} mm` : '—'}
          </span>
        </div>
        <div className={styles.contextItem}>
          <span className={styles.contextLabel}>💨 Vent ETD</span>
          <span className={styles.contextValue}>
            {result.meteo.etd_wind_speed_kmh != null
              ? `${result.meteo.etd_wind_speed_kmh} km/h` : '—'}
          </span>
        </div>
        <div className={styles.contextItem}>
          <span className={styles.contextLabel}>🌡️ Temp. ETD</span>
          <span className={styles.contextValue}>
            {result.meteo.etd_temperature_max != null
              ? `${result.meteo.etd_temperature_max}°C` : '—'}
          </span>
        </div>
        <div className={styles.contextItem}>
          <span className={styles.contextLabel}>🌧️ Pluie ETA</span>
          <span className={styles.contextValue}>
            {result.meteo.eta_precipitation_mm != null
              ? `${result.meteo.eta_precipitation_mm} mm` : '—'}
          </span>
        </div>
        <div className={styles.contextItem}>
          <span className={styles.contextLabel}>💨 Vent ETA</span>
          <span className={styles.contextValue}>
            {result.meteo.eta_wind_speed_kmh != null
              ? `${result.meteo.eta_wind_speed_kmh} km/h` : '—'}
          </span>
        </div>
        <div className={styles.contextItem}>
          <span className={styles.contextLabel}>🌡️ Temp. ETA</span>
          <span className={styles.contextValue}>
            {result.meteo.eta_temperature_max != null
              ? `${result.meteo.eta_temperature_max}°C` : '—'}
          </span>
        </div>
      </div>
    </>
  )}
</div>

              </div>
            )}
          </div>

        </div>
      </div>
    </AppLayout>
  )
}