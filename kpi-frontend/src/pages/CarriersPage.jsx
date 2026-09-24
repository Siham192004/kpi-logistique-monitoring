import React, { useState, useEffect } from 'react'
import { AppLayout } from '../components/layout/AppLayout'
import { Header } from '../components/layout/Header'
import { DataTable } from '../components/ui/Table'
import { Badge, niveauToBadge, niveauLabel } from '../components/ui/Badge'
import { SkeletonTable, SkeletonChart } from '../components/ui/Skeleton'
import { apiFetch } from '../store/auth'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, Cell
} from 'recharts'
import { Anchor, Download } from 'lucide-react'
import styles from './CarriersPage.module.css'

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: '10px 14px', boxShadow: 'var(--shadow-lg)', fontSize: '12px' }}>
      <p style={{ color: 'var(--color-text-secondary)', marginBottom: 4, fontWeight: 500 }}>{label}</p>
      {payload.map(p => (
        <p key={p.name} style={{ color: p.color || 'var(--color-accent)', fontWeight: 600 }}>
          {p.name}: {p.value?.toFixed(1)}%
        </p>
      ))}
    </div>
  )
}

export const CarriersPage = () => {
  const [carriers, setCarriers]                     = useState([])
  const [loading, setLoading]                       = useState(true)
  const [selected, setSelected]                     = useState(null)
  const [selectedCarrierChart, setSelectedCarrierChart] = useState('')
  const [selectedAnnee, setSelectedAnnee]           = useState('')
  const [mensuelData, setMensuelData]               = useState([])
  const [loadingChart, setLoadingChart]             = useState(false)
  const [refreshVersion, setRefreshVersion]         = useState(0)
  const anneesDisponibles                           = ['2024', '2025', '2026']

  useEffect(() => {
    const handleKpiDataUpdated = () => setRefreshVersion(version => version + 1)
    window.addEventListener('kpi_data_updated', handleKpiDataUpdated)
    return () => window.removeEventListener('kpi_data_updated', handleKpiDataUpdated)
  }, [])

  useEffect(() => {
    apiFetch('/kpis/rapport-carriers')
      .then(data => {
        setCarriers(data)
        setSelected(current => data.find(item => item.carrier === current?.carrier) ?? data[0] ?? null)
      })
      .finally(() => setLoading(false))
  }, [refreshVersion])

  useEffect(() => {
    if (carriers.length > 0 && !selectedCarrierChart) {
      setSelectedCarrierChart(carriers[0].carrier)
    }
  }, [carriers])

  useEffect(() => {
  setLoadingChart(true)
  const params = new URLSearchParams()
  if (selectedAnnee) params.set('annee', selectedAnnee)
  if (selected?.carrier) params.set('carrier', selected.carrier)
  apiFetch(`/kpis/rapport-carriers-mensuel?${params}`)
    .then(setMensuelData)
    .catch(() => setMensuelData([]))
    .finally(() => setLoadingChart(false))
}, [selected, selectedAnnee])

  const handleExportExcel = async () => {
    const res = await fetch('/api/export/excel/carriers', {
      headers: { Authorization: `Bearer ${localStorage.getItem('kpi_token')}` }
    })
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = 'carriers.xlsx'; a.click()
  }

  const columns = [
    {
      key: 'carrier', label: 'Carrier', sortable: true,
      render: (v) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 28, height: 28, borderRadius: 8, background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Anchor size={12} color="var(--color-text-tertiary)" />
          </div>
          <span style={{ fontWeight: 500, color: 'var(--color-text-primary)' }}>{v}</span>
        </div>
      )
    },
    { key: 'kpi1', label: 'KPI1 (Vol. chargé)', sortable: true, align: 'right',
      render: (v) => v != null ? <span style={{ fontVariantNumeric: 'tabular-nums', color: v >= 95 ? 'var(--color-success)' : v >= 85 ? 'var(--color-warning)' : 'var(--color-danger)' }}>{v.toFixed(1)}%</span> : '—'
    },
    { key: 'kpi2', label: 'KPI2 (Vol. alloué)', sortable: true, align: 'right',
      render: (v) => v != null ? <span style={{ fontVariantNumeric: 'tabular-nums' }}>{v.toFixed(1)}%</span> : '—'
    },
    { key: 'kpi4', label: 'KPI4 (Modif./Annul.)', sortable: true, align: 'right',
      render: (v) => v != null ? <span style={{ fontVariantNumeric: 'tabular-nums', color: v <= 10 ? 'var(--color-success)' : v <= 20 ? 'var(--color-warning)' : 'var(--color-danger)' }}>{v.toFixed(1)}%</span> : '—'
    },
    { key: 'kpi5', label: 'KPI5 (Retards)', sortable: true, align: 'right',
      render: (v) => v != null ? <span style={{ fontVariantNumeric: 'tabular-nums', color: v <= 20 ? 'var(--color-success)' : v <= 40 ? 'var(--color-warning)' : 'var(--color-danger)' }}>{v.toFixed(1)}%</span> : '—'
    },
    { key: 'effectif', label: 'Shipments', sortable: true, align: 'right', render: (v) => v?.toLocaleString('fr-FR') },
    { key: 'niveau_global', label: 'Niveau global',
      render: (v) => v ? <Badge variant={niveauToBadge(v)} dot size="sm">{niveauLabel(v)}</Badge> : '—'
    },
  ]

  const radarData = selected ? [
    { subject: 'KPI1',      value: selected.kpi1 ?? 0, fullMark: 100 },
    { subject: 'KPI2',      value: selected.kpi2 ?? 0, fullMark: 100 },
    { subject: 'KPI4 (inv)', value: selected.kpi4 != null ? 100 - selected.kpi4 : 0, fullMark: 100 },
    { subject: 'KPI5 (inv)', value: selected.kpi5 != null ? 100 - selected.kpi5 : 0, fullMark: 100 },
  ] : []

  return (
    <AppLayout>
      <Header title="Rapport Carriers" subtitle={`${carriers.length} transporteurs analysés`}
        actions={
          <button onClick={handleExportExcel} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 'var(--radius-md)', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', color: 'var(--color-text-primary)', cursor: 'pointer', fontSize: 12 }}>
            <Download size={13}/> Excel
          </button>
        }
      />

      <div className={styles.content}>

        {/* Summary cards */}
        {!loading && carriers.length > 0 && (
          <div className={styles.summary}>
            {[
              { label: 'On target',    count: carriers.filter(c => c.niveau_global === 'On target').length,  color: 'var(--color-success)' },
              { label: 'À surveiller', count: carriers.filter(c => c.niveau_global === 'To monitor').length, color: 'var(--color-warning)' },
              { label: 'Critique',     count: carriers.filter(c => c.niveau_global === 'Critical').length,   color: 'var(--color-danger)' },
              { label: 'Total carriers', count: carriers.length, color: 'var(--color-text-secondary)' },
            ].map(({ label, count, color }) => (
              <div key={label} className={styles.summaryCard}>
                <span className={styles.summaryCount} style={{ color }}>{count}</span>
                <span className={styles.summaryLabel}>{label}</span>
              </div>
            ))}
          </div>
        )}

        

        {/* Charts row */}
        <div className={styles.chartsRow}>

          {/* Graphique mensuel */}
<div className={styles.chartCard}>
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
    <h3 className={styles.chartTitle} style={{ margin: 0 }}>
      Score global mensuel — {selected?.carrier || 'Tous les carriers'}
    </h3>
    <select
      value={selectedAnnee}
      onChange={e => setSelectedAnnee(e.target.value)}
      style={{ height: 28, padding: '0 8px', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', color: 'var(--color-text-primary)', fontSize: 11 }}
    >
      <option value="">Toutes les années</option>
      {anneesDisponibles.map(a => <option key={a} value={a}>{a}</option>)}
    </select>
  </div>
  {loadingChart
    ? <SkeletonChart height={240} />
    : (
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={mensuelData} margin={{ top: 4, right: 4, left: -16, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
          <XAxis dataKey="mois" tick={{ fill: 'rgba(255,255,255,0.35)', fontSize: 10 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fill: 'rgba(255,255,255,0.35)', fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={v => `${v}%`} domain={[0, 100]} />
          <Tooltip content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const d = payload[0]?.payload
            return (
              <div style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: '10px 14px', fontSize: 12 }}>
                <p style={{ color: 'var(--color-text-secondary)', marginBottom: 6, fontWeight: 600 }}>{label}</p>
                <p style={{ color: d?.color, fontWeight: 700, marginBottom: 4 }}>Score global : {d?.score}%</p>
                <p style={{ color: 'rgba(255,255,255,0.5)' }}>KPI1 : {d?.kpi1}%</p>
                <p style={{ color: 'rgba(255,255,255,0.5)' }}>KPI2 : {d?.kpi2}%</p>
                <p style={{ color: 'rgba(255,255,255,0.5)' }}>KPI4 : {d?.kpi4}%</p>
                <p style={{ color: 'rgba(255,255,255,0.5)' }}>KPI5 : {d?.kpi5}%</p>
              </div>
            )
          }} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="score" radius={[4,4,0,0]} maxBarSize={40}>
            {mensuelData.map((entry, index) => (
              <Cell key={index} fill={entry.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    )
  }
</div>

          {/* Radar */}
          <div className={styles.chartCard}>
            <h3 className={styles.chartTitle}>Performance radar — {selected?.carrier || '—'}</h3>
            {selected && (
              <ResponsiveContainer width="100%" height={240}>
                <RadarChart data={radarData}>
                  <PolarGrid stroke="rgba(255,255,255,0.08)" />
                  <PolarAngleAxis dataKey="subject" tick={{ fill: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
                  <Radar dataKey="value" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.15} strokeWidth={2} />
                </RadarChart>
              </ResponsiveContainer>
            )}
          </div>

        </div>

        {/* Table */}
        {loading
          ? <SkeletonTable rows={6} cols={7} />
          : (
            <DataTable
              columns={columns}
              data={carriers}
              rowKey="carrier"
              onRowClick={setSelected}
              emptyMessage="Aucun carrier disponible"
            />
          )
        }

      </div>
    </AppLayout>
  )
}
