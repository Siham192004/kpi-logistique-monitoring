import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppLayout } from '../components/layout/AppLayout'
import { Header } from '../components/layout/Header'
import { FilterBar } from '../components/features/FilterBar'
import { KPICard } from '../components/features/KPICard'
import { SkeletonKPICard, SkeletonChart } from '../components/ui/Skeleton'
import { apiFetch } from '../store/auth'
import { useAuthStore } from '../store/auth'
import { Badge } from '../components/ui/Badge'
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { TrendingUp, AlertTriangle, Ship, Activity, Calendar } from 'lucide-react'
import toast from 'react-hot-toast'
import styles from './DashboardPage.module.css'
import { Download } from 'lucide-react'
import { useRef } from 'react'
// Ajouter après les autres imports
import domtoimage from 'dom-to-image-more'

const CHART_COLORS = {
  'On target': '#10b981',
  'To monitor': '#f59e0b',
  'Critical':  '#ef4444',
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: 'var(--color-surface-2)',
      border: '1px solid var(--color-border)',
      borderRadius: 'var(--radius-md)',
      padding: '10px 14px',
      boxShadow: 'var(--shadow-lg)',
      fontSize: '12px',
    }}>
      <p style={{ color: 'var(--color-text-secondary)', marginBottom: '4px', fontWeight: 500 }}>{label}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color || 'var(--color-accent)', fontWeight: 600 }}>
          {p.value?.toFixed(1)}{p.unit || ''}
        </p>
      ))}
    </div>
  )
}

export const DashboardPage = () => {
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const [filters, setFilters] = useState({ mois: null, carrier: null})
  const [filtres, setFiltres] = useState(null)
  const [dashboard, setDashboard] = useState(null)
  const [loading, setLoading] = useState(true)
  
  // Load filter options once
  useEffect(() => {
    apiFetch('/kpis/filtres')
      .then(setFiltres)
      .catch(() => {})
  }, [])

  // Load dashboard KPIs
  const loadDashboard = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (filters.mois)    params.set('mois', filters.mois)
      if (filters.carrier) params.set('carrier', filters.carrier)
      const data = await apiFetch(`/kpis/dashboard?${params}`)
      setDashboard(data)
    } catch (err) {
      toast.error('Erreur lors du chargement du dashboard')
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => { loadDashboard() }, [loadDashboard])

  const pageRef = useRef(null)

const handleExportPNG = () => {
  const element = pageRef.current
  domtoimage.toPng(element, {
    quality: 1,
    bgcolor: '#131620',
    style: {
      backgroundColor: '#131620',
    }
  }).then(dataUrl => {
    const a = document.createElement('a')
    a.href = dataUrl
    a.download = `dashboard-kpi-${new Date().toISOString().slice(0,10)}.png`
    a.click()
  }).catch(err => {
    console.error('Export failed:', err)
    toast.error('Erreur lors de l\'export PNG')
  })
}

  const kpis = ['KPI1', 'KPI2', 'KPI3', 'KPI4', 'KPI5']
  const handleExportExcel = async () => {
  const res = await fetch('/api/export/excel/shipments', {
    headers: { Authorization: `Bearer ${localStorage.getItem('kpi_token')}` }
  })
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = 'shipments.xlsx'; a.click()
}

  return (
    <AppLayout>
      <Header 
        title="Dashboard KPI"
        subtitle={`Performance maritime — ${new Date().toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}`}
        actions={
        <button onClick={handleExportPNG} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 'var(--radius-md)', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', color: 'var(--color-text-primary)', cursor: 'pointer', fontSize: 12 }}>
          <Download size={13}/> PNG
        </button>
      }
      />

      <FilterBar
        filters={filters}
        onChange={setFilters}
        filtres={filtres}
        loading={loading}
        onRefresh={loadDashboard}
      />

      <div ref={pageRef} data-export className={styles.content}>
        {/* KPI Grid */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>
              <Activity size={15} />
              Indicateurs clés
            </h2>
            {dashboard && (
              <Badge variant="accent" size="sm">
                {Object.values(filters).filter(Boolean).length > 0 ? 'Filtres actifs' : 'Vue globale'}
              </Badge>
            )}
          </div>
          

          <div className={styles.kpiGrid}>
            {loading
              ? kpis.map((k) => <SkeletonKPICard key={k} />)
              : kpis.map((kpiId, i) => {
                  const kpiKey = kpiId.toLowerCase()
                  return (
                    <KPICard
                      key={kpiId}
                      kpiId={kpiId}
                      data={dashboard?.[kpiKey]}
                      index={i}
                      onClick={() => navigate(`/kpis?kpi=${kpiId}`)}
                    />
                  )
                })
            }
          </div>
        </section>

              </div>
    </AppLayout>
  )
}

