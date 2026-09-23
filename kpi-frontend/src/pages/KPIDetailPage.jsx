import React, { useState, useEffect } from 'react'
import { useSearchParams, useLocation } from 'react-router-dom'
import { AppLayout } from '../components/layout/AppLayout'
import { Header } from '../components/layout/Header'
import { Badge, niveauToBadge, niveauLabel } from '../components/ui/Badge'
import { DataTable } from '../components/ui/Table'
import { SkeletonChart, SkeletonTable } from '../components/ui/Skeleton'
import { apiFetch } from '../store/auth'
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, LineChart, Line
} from 'recharts'
import styles from './KPIDetailPage.module.css'
import { useRef } from 'react'
import html2canvas from 'html2canvas'
import { Download } from 'lucide-react'

const TABS = ['KPI1', 'KPI2', 'KPI3', 'KPI4', 'KPI5']
const KPI_LABELS = {
  KPI1: '% Volume chargé / alloué',
  KPI2: '% Volume alloué / réservé',
  KPI3: 'Retards en transbordement',
  KPI4: 'Modifications & annulations',
  KPI5: 'Déviation ETA vs ATA',
}
const STATUS_COLORS = { 'On target': '#10b981', 'To monitor': '#f59e0b', 'Critical': '#ef4444' }

const YEARS = Array.from({ length: 2050 - 2022 + 1 }, (_, i) => String(2022 + i))

const MONTH_ORDER = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December'
]
const MONTH_FR = {
  January:'Jan', February:'Fév', March:'Mar', April:'Avr',
  May:'Mai', June:'Jun', July:'Juil', August:'Aoû',
  September:'Sep', October:'Oct', November:'Nov', December:'Déc'
}

function sortAndLabelMonths(items) {
  return [...items]
    .sort((a, b) => {
      const mA = a.groupe.split(' ')[0]
      const mB = b.groupe.split(' ')[0]
      return MONTH_ORDER.indexOf(mA) - MONTH_ORDER.indexOf(mB)
    })
    .map(item => ({
      ...item,
      groupeAffiche: MONTH_FR[item.groupe.split(' ')[0]] || item.groupe.split(' ')[0],
    }))
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className={styles.tooltip}>
      <p className={styles.tooltipLabel}>{label}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color || '#3b82f6', fontWeight: 600, fontSize: '13px' }}>
          {typeof p.value === 'number' ? p.value.toFixed(1) : p.value}{p.unit || ''}
        </p>
      ))}
    </div>
  )
}

const PieTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  return (
    <div className={styles.tooltip}>
      <p style={{ color: payload[0].color, fontWeight: 600 }}>{payload[0].name}</p>
      <p style={{ color: 'var(--color-text-primary)', fontSize: '13px' }}>{payload[0].value}</p>
    </div>
  )
}

export const KPIDetailPage = () => {
  const [params] = useSearchParams()
  const [activeTab,         setActiveTab]         = useState(params.get('kpi') || 'KPI1')
  const [groupBy,           setGroupBy]           = useState('carrier')
  const [selectedYear,      setSelectedYear]      = useState('')
  const [selectedCarrier,   setSelectedCarrier]   = useState('')
  const [carriers,          setCarriers]          = useState([])
  const [chartData,         setChartData]         = useState(null)
  const [detailData,        setDetailData]        = useState(null)
  const [loading,           setLoading]           = useState(true)
  const [selectedCategorie, setSelectedCategorie] = useState(null)
  const chartRef = useRef(null)
  const location = useLocation()

  const handleExportPNG = () => {
    html2canvas(chartRef.current).then(canvas => {
      const a = document.createElement('a')
      a.href = canvas.toDataURL('image/png')
      a.download = `kpi-${activeTab}.png`
      a.click()
    })
  }

  // Charger les carriers une seule fois au montage
  useEffect(() => {
    apiFetch('/kpis/filtres')
      .then(d => setCarriers(d.carriers || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    let cancelled = false

    setLoading(true)
    setChartData(null)
    setDetailData(null)
    setSelectedCategorie(null)

    const queryParts = []
    if (selectedYear)    queryParts.push(`annee=${selectedYear}`)
    if (selectedCarrier) queryParts.push(`carrier=${encodeURIComponent(selectedCarrier)}`)
    const query = queryParts.length > 0 ? `?${queryParts.join('&')}` : ''

    const fetches = []

    if (['KPI1', 'KPI2', 'KPI4', 'KPI5'].includes(activeTab)) {
      fetches.push(apiFetch(`/kpis/${activeTab}/groupe/${groupBy}${query}`)
        .then(d => { if (!cancelled) setChartData(d) }))
    }

    if (activeTab === 'KPI3') {
      fetches.push(apiFetch(`/kpis/kpi3/detail${query}`)
        .then(d => { if (!cancelled) setDetailData(d) }))
    }
    if (activeTab === 'KPI4') {
      fetches.push(apiFetch(`/kpis/kpi4/detail${query}`)
        .then(d => { if (!cancelled) setDetailData(d) }))
    }
    if (activeTab === 'KPI5') {
      fetches.push(apiFetch(`/kpis/kpi5/detail${query}`)
        .then(d => { if (!cancelled) setDetailData(d) }))
    }

    Promise.all(fetches).finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [activeTab, groupBy, selectedYear, selectedCarrier, location.key])

  const processedItems = (() => {
    const raw = chartData?.items || []
    if (groupBy === 'month') return sortAndLabelMonths(raw)
    return raw.map(item => ({ ...item, groupeAffiche: item.groupe }))
  })()

  const kpi4PieData = detailData && activeTab === 'KPI4' ? [
    { name: 'Normal',  value: detailData.pct_normaux,  color: '#10b981' },
    { name: 'Modifié', value: detailData.pct_modifies, color: '#f59e0b' },
    { name: 'Annulé',  value: detailData.pct_annules,  color: '#ef4444' },
  ] : []

  const kpi5PieData = detailData && activeTab === 'KPI5' ? [
    { name: "À l'heure", value: detailData.nb_a_lheure,  color: '#10b981' },
    { name: 'En retard',  value: detailData.nb_en_retard, color: '#ef4444' },
  ] : []

  const NIVEAU_COLORS = {
    'On target': '#10b981',
    'To monitor': '#f59e0b',
    'Critical': '#ef4444',
  }

  const kpi3Columns = [
    { key: 'shipment_id', label: '#',
      render: v => <span style={{ fontSize: '11px', fontFamily: 'monospace' }}>#{v}</span> },
    { key: 'carrier',          label: 'Carrier',   sortable: true },
    { key: 'vessel_nom',       label: 'Navire',    sortable: true },
    { key: 'month',            label: 'Mois',      sortable: true },
    { key: 'etd_deviation',    label: 'Dév. ETD',  sortable: true, align: 'right',
      render: v => v != null ? `${v.toFixed(1)} j` : '—' },
    { key: 'eta_deviation',    label: 'Dév. ETA',  sortable: true, align: 'right',
      render: v => v != null ? `${v.toFixed(1)} j` : '—' },
    { key: 'categorie_metier', label: 'Catégorie', sortable: true,
      render: v => v || '—' },
    { key: 'niveau_global',    label: 'Niveau',
      render: v => v
        ? <Badge variant={niveauToBadge(v)} size="sm">{niveauLabel(v)}</Badge>
        : '—'
    },
  ]

  const selectStyle = {
    background: 'var(--color-surface-2)',
    border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius-md)',
    color: 'var(--color-text-primary)',
    fontSize: 12,
    padding: '5px 10px',
    cursor: 'pointer',
  }

  return (
    <AppLayout>
      <Header title="Analyse KPI" subtitle="Détail et distribution par indicateur"
        actions={
          <button onClick={handleExportPNG} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 'var(--radius-md)', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', color: 'var(--color-text-primary)', cursor: 'pointer', fontSize: 12 }}>
            <Download size={13}/> PNG
          </button>
        }
      />

      <div className={styles.tabs}>
        {TABS.map(tab => (
          <button
            key={tab}
            className={`${styles.tab} ${activeTab === tab ? styles.activeTab : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className={styles.content} key={activeTab} ref={chartRef}>

        <div className={styles.tabHead}>
          <h2 className={styles.tabTitle}>{KPI_LABELS[activeTab]}</h2>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {/* Filtre Année */}
            <select
              style={selectStyle}
              value={selectedYear}
              onChange={e => setSelectedYear(e.target.value)}
            >
              <option value="">Toutes les années</option>
              {YEARS.map(year => (
                <option key={year} value={year}>{year}</option>
              ))}
            </select>

            {/* Filtre Carrier */}
            <select
              style={selectStyle}
              value={selectedCarrier}
              onChange={e => setSelectedCarrier(e.target.value)}
            >
              <option value="">Tous les carriers</option>
              {carriers.map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Charts KPI1/2/4/5 */}
        {['KPI1', 'KPI2', 'KPI4', 'KPI5'].includes(activeTab) && (
          <div className={styles.chartCard}>
            <div className={styles.chartHeader}>
              <h3 className={styles.chartTitle}>Groupé par</h3>
              <div className={styles.groupBtns}>
                {['carrier', 'month'].map(g => (
                  <button
                    key={g}
                    className={`${styles.groupBtn} ${groupBy === g ? styles.activeGroup : ''}`}
                    onClick={() => setGroupBy(g)}
                  >
                    {g === 'carrier' ? 'Carrier' : 'Mois'}
                  </button>
                ))}
              </div>
            </div>

            {loading ? <SkeletonChart height={260} /> : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={processedItems} margin={{ top: 4, right: 8, left: -16, bottom: 50 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                  <XAxis
                    dataKey="groupeAffiche"
                    tick={{ fill: 'rgba(255,255,255,0.35)', fontSize: 10 }}
                    angle={-35} textAnchor="end" interval={0}
                    tickLine={false} axisLine={false}
                  />
                  <YAxis
                    tick={{ fill: 'rgba(255,255,255,0.35)', fontSize: 10 }}
                    tickLine={false} axisLine={false}
                    tickFormatter={v => `${v}%`}
                  />
                  <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                  <Bar dataKey="valeur" radius={[4,4,0,0]} unit="%" maxBarSize={44}>
                    {processedItems.map((entry, i) => (
                      <Cell key={i} fill={STATUS_COLORS[entry.niveau] || '#3b82f6'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        )}

        {/* KPI3 */}
        {activeTab === 'KPI3' && (
          <div>
            {loading && <SkeletonTable rows={3} cols={4} />}
            {!loading && Array.isArray(detailData?.repartition) && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '20px' }}>
                {detailData.repartition.map((item, i) => (
                  <div key={i}
                    onClick={() => setSelectedCategorie(
                      selectedCategorie === item.categorie ? null : item.categorie
                    )}
                    style={{
                      background: 'var(--color-surface)',
                      border: `2px solid ${
                        selectedCategorie === item.categorie
                          ? NIVEAU_COLORS[item.niveau]
                          : item.nombre > 0 ? NIVEAU_COLORS[item.niveau] + '40' : 'var(--color-border)'
                      }`,
                      borderRadius: 'var(--radius-md)',
                      padding: '10px 14px',
                      minWidth: '160px',
                      flex: '1',
                      cursor: item.nombre > 0 ? 'pointer' : 'default',
                      opacity: selectedCategorie && selectedCategorie !== item.categorie ? 0.45 : 1,
                      transition: 'all 0.15s ease',
                    }}>
                    <div style={{
                      fontSize: '22px', fontWeight: 700,
                      color: item.nombre > 0 ? NIVEAU_COLORS[item.niveau] : 'var(--color-text-tertiary)',
                    }}>
                      {item.nombre}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
                      {item.categorie}
                    </div>
                    <Badge variant={niveauToBadge(item.niveau)} size="sm" style={{ marginTop: '6px' }}>
                      {niveauLabel(item.niveau)}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
            {!loading && (
              <DataTable
                columns={kpi3Columns}
                data={(() => {
                  const all = Array.isArray(detailData?.shipments_critiques) ? detailData.shipments_critiques : []
                  if (!selectedCategorie) return all
                  return all.filter(s => s.categorie_metier === selectedCategorie)
                })()}
                rowKey="shipment_id"
                emptyMessage="Aucun shipment pour cette catégorie"
              />
            )}
          </div>
        )}

        {/* KPI4 */}
        {activeTab === 'KPI4' && detailData && (
          <div className={styles.row}>
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>Répartition des statuts</h3>
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={kpi4PieData} dataKey="value" nameKey="name"
                    cx="50%" cy="45%" outerRadius={75} innerRadius={45} paddingAngle={3}>
                    {kpi4PieData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                  </Pie>
                  <Tooltip content={<PieTooltip />} />
                  <Legend
                    wrapperStyle={{ fontSize: '12px', paddingTop: '8px' }}
                    formatter={(value, entry) => (
                      <span style={{ color: entry.color, fontWeight: 500 }}>
                        {value} ({entry.payload.value}%)
                      </span>
                    )}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className={styles.chartCard}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <h3 className={styles.chartTitle} style={{ margin: 0 }}>Évolution mensuelle des statuts</h3>
                <select
                  style={selectStyle}
                  value={selectedCarrier}
                  onChange={e => setSelectedCarrier(e.target.value)}
                >
                  <option value="">Tous les carriers</option>
                  {carriers.map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
              {Array.isArray(detailData.par_mois) && detailData.par_mois.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={detailData.par_mois} margin={{ top: 8, right: 16, left: -16, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                    <XAxis dataKey="month" tick={{ fill: 'rgba(255,255,255,0.35)', fontSize: 11 }} tickLine={false} axisLine={false} />
                    <YAxis tick={{ fill: 'rgba(255,255,255,0.35)', fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
                    <Tooltip contentStyle={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 8, fontSize: 12 }} />
                    <Legend wrapperStyle={{ fontSize: '12px' }} />
                    <Line type="monotone" dataKey="normal"  name="Normal"  stroke="#10b981" strokeWidth={2} dot={{ r: 3, fill: '#10b981' }} activeDot={{ r: 5 }} />
                    <Line type="monotone" dataKey="modifie" name="Modifié" stroke="#f59e0b" strokeWidth={2} dot={{ r: 3, fill: '#f59e0b' }} activeDot={{ r: 5 }} />
                    <Line type="monotone" dataKey="annule"  name="Annulé"  stroke="#ef4444" strokeWidth={2} dot={{ r: 3, fill: '#ef4444' }} activeDot={{ r: 5 }} />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-tertiary)', fontSize: 13 }}>
                  Aucune donnée mensuelle disponible
                </div>
              )}
            </div>
          </div>
        )}

        {/* KPI5 */}
        {activeTab === 'KPI5' && detailData && (
          <div className={styles.row}>
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>Répartition ponctualité</h3>
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie data={kpi5PieData} dataKey="value" nameKey="name"
                    cx="50%" cy="50%" outerRadius={80} innerRadius={50} paddingAngle={3}>
                    {kpi5PieData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                  </Pie>
                  <Tooltip content={<PieTooltip />} />
                  <Legend wrapperStyle={{ fontSize: '12px', color: 'var(--color-text-secondary)' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>Taux de retard</h3>
              <div className={styles.kpi4Stats}>
                <div className={styles.bigStat}>
                  <span className={styles.bigStatVal} style={{ color: 'var(--color-success)' }}>
                    {detailData.pct_a_lheure != null ? `${detailData.pct_a_lheure.toFixed(1)}%` : '—'}
                  </span>
                  <span className={styles.bigStatLabel}>À l'heure</span>
                  <span style={{ fontSize: '11px', color: 'var(--color-text-tertiary)', marginTop: '4px' }}>
                    {detailData.nb_a_lheure} shipments
                  </span>
                </div>
                <div className={styles.divider} />
                <div className={styles.bigStat}>
                  <span className={styles.bigStatVal} style={{ color: 'var(--color-danger)' }}>
                    {detailData.pct_en_retard != null ? `${detailData.pct_en_retard.toFixed(1)}%` : '—'}
                  </span>
                  <span className={styles.bigStatLabel}>En retard</span>
                  <span style={{ fontSize: '11px', color: 'var(--color-text-tertiary)', marginTop: '4px' }}>
                    {detailData.nb_en_retard} shipments
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}

      </div>
    </AppLayout>
  )
}