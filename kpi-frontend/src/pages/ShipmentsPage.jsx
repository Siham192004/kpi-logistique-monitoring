import React, { useState, useEffect, useCallback, useRef } from 'react'
import { AppLayout } from '../components/layout/AppLayout'
import { Header } from '../components/layout/Header'
import { DataTable } from '../components/ui/Table'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Modal, ConfirmModal } from '../components/ui/Modal'
import { Input, Select, Textarea } from '../components/ui/Input'
import { SkeletonTable } from '../components/ui/Skeleton'
import { apiFetch } from '../store/auth'
import { useAuthStore } from '../store/auth'
import { Plus, Search, Pencil, Trash2, Eye, ChevronDown } from 'lucide-react'
import toast from 'react-hot-toast'
import styles from './ShipmentsPage.module.css'

const INCOTERMS = ['CIF', 'FOB', 'CFR', 'DAP', 'FCA']

const REQUIRED_FIELDS = [
  'carrier', 'vessel_nom', 'port_chargement', 'port_dechargement',
  'pays_destination', 'etd', 'eta', 'transit_time', 'frequency',
  'volume_booked', 'confirmed_volume', 'incoterm'
]

const FIELD_LABELS = {
  carrier:          'Carrier',
  vessel_nom:       'Navire',
  port_chargement:  'Port de chargement',
  port_dechargement:'Port de déchargement',
  pays_destination: 'Pays destination',
  etd:              'ETD',
  eta:              'ETA',
  transit_time:     'Transit time',
  frequency:        'Fréquence',
  volume_booked:    'Volume réservé',
  confirmed_volume: 'Volume confirmé',
  incoterm:         'Incoterm',
}

const FREQUENCY_REGEX = /^\d+j$/

const statusVariant = (s) => {
  if (!s) return 'default'
  if (s === 'Normal') return 'success'
  if (s === 'Cancelled') return 'danger'
  return 'default'
}

/* ── CarrierCombobox ── */
const CarrierCombobox = ({ value, onChange, carriers, onAddCarrier }) => {
  const [open, setOpen]     = useState(false)
  const [query, setQuery]   = useState(value || '')
  const [adding, setAdding] = useState(false)
  const ref                 = useRef(null)

  useEffect(() => { setQuery(value || '') }, [value])

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const filteredCarriers = carriers.filter(c => c.toLowerCase().includes(query.toLowerCase()))
  const canAdd = query.trim() && !carriers.find(c => c.toLowerCase() === query.trim().toLowerCase())

  const select = (c) => { onChange(c); setQuery(c); setOpen(false) }

  const handleAdd = async () => {
    setAdding(true)
    await onAddCarrier(query.trim())
    select(query.trim())
    setAdding(false)
  }

  return (
    <div className={styles.comboWrap} ref={ref}>
      <label className={styles.comboLabel}>Carrier *</label>
      <div className={`${styles.comboBox} ${open ? styles.comboBoxOpen : ''}`}>
        <input
          className={styles.comboInput}
          value={query}
          onChange={e => { setQuery(e.target.value); onChange(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          placeholder="Rechercher ou ajouter un carrier..."
        />
        <ChevronDown size={13} className={styles.comboChevron} />
      </div>
      {open && (
        <div className={styles.comboDropdown}>
          {filteredCarriers.length === 0 && !canAdd && (
            <div className={styles.comboEmpty}>Aucun carrier trouvé</div>
          )}
          {filteredCarriers.map(c => (
            <div
              key={c}
              className={`${styles.comboOption} ${c === value ? styles.comboOptionActive : ''}`}
              onMouseDown={() => select(c)}
            >
              {c}
            </div>
          ))}
          {canAdd && (
            <div className={styles.comboAdd} onMouseDown={handleAdd}>
              {adding ? 'Ajout...' : `+ Ajouter "${query.trim()}"`}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ── Page principale ── */
export const ShipmentsPage = () => {
  const { user } = useAuthStore()
  const isOperateur = user?.role === 'Control Tower Team'

  const [shipments, setShipments]         = useState([])
  const [supprimes, setSupprimes]         = useState([])
  const [carriers, setCarriers]           = useState([])
  const [loading, setLoading]             = useState(true)
  const [search, setSearch]               = useState('')
  const [filterCarrier, setFilterCarrier] = useState('')
  const [activeTab, setActiveTab]         = useState('tous')   // ← ici
  const [createOpen, setCreateOpen]       = useState(false)
  const [editTarget, setEditTarget]       = useState(null)
  const [deleteTarget, setDeleteTarget]   = useState(null)
  const [detailTarget, setDetailTarget]   = useState(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [form, setForm]                   = useState(emptyForm())
  const [errors, setErrors]               = useState({})

  function emptyForm() {
    return {
      carrier: '', vessel_nom: '', port_chargement: '', port_dechargement: '',
      pays_destination: '', shipment_status: 'Normal',
      etd: '', eta: '', atd: '', ata: '',
      incoterm: '', volume_booked: '', confirmed_volume: '', charged_volume: '',
      transit_time: '', frequency: '',
    }
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (filterCarrier) params.set('carrier', filterCarrier)
      const [s, c, sup] = await Promise.all([
        apiFetch(`/shipments/?${params}`),
        apiFetch('/shipments/carriers'),
        apiFetch('/shipments/supprimes/liste'),
      ])
      setShipments(s)
      setCarriers(c.map(x => x.carrier || x))
      setSupprimes(sup)
    } catch (e) {
      toast.error('Erreur de chargement')
    } finally {
      setLoading(false)
    }
  }, [filterCarrier])

  useEffect(() => { load() }, [load])

  // ── Filtrage avec onglets ──
 const dataSource = activeTab === 'supprimes' ? supprimes : shipments

const filtered = dataSource.filter(s => {
    const matchSearch = !search || [s.carrier, s.vessel_nom, s.port_chargement, s.port_dechargement, s.operateur_prenom, s.operateur_nom, [s.operateur_prenom, s.operateur_nom].filter(Boolean).join(' ')]
      .some(v => v?.toLowerCase().includes(search.toLowerCase()))

    const matchCarrier = !filterCarrier || s.carrier === filterCarrier

    const matchTab =
      activeTab === 'tous'      ? true :
      activeTab === 'en_cours'  ? (s.shipment_status === 'Normal' && !s.ata) :
      activeTab === 'termines'  ? (s.shipment_status === 'Normal' && !!s.ata) :
      activeTab === 'annules'   ? (s.shipment_status === 'Cancelled') :
      activeTab === 'supprimes' ? true :
      true

    return matchSearch && matchCarrier && matchTab
  })

  const validate = () => {
    const errs = {}
    REQUIRED_FIELDS.forEach(field => {
      if (!form[field] || String(form[field]).trim() === '') {
        errs[field] = `${FIELD_LABELS[field]} est obligatoire`
      }
    })
    if (form.frequency && !FREQUENCY_REGEX.test(form.frequency.trim())) {
      errs.frequency = 'Format invalide — utilisez le format : 7j, 14j, 30j…'
    }
    if (form.transit_time && (isNaN(form.transit_time) || +form.transit_time <= 0)) {
      errs.transit_time = 'Transit time doit être un nombre positif'
    }
    if (form.etd && form.eta && new Date(form.eta) < new Date(form.etd)) {
      errs.eta = 'ETA doit être après ETD'
    }
    if (form.volume_booked && (isNaN(form.volume_booked) || +form.volume_booked <= 0)) {
      errs.volume_booked = 'Volume doit être un nombre positif'
    }
    if (form.confirmed_volume && (isNaN(form.confirmed_volume) || +form.confirmed_volume <= 0)) {
      errs.confirmed_volume = 'Volume doit être un nombre positif'
    }
    if (form.charged_volume && (isNaN(form.charged_volume) || +form.charged_volume <= 0)) {
      errs.charged_volume = 'Volume doit être un nombre positif'
    }
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleAddCarrier = async (name) => {
    try {
      await apiFetch('/shipments/carriers', { method: 'POST', body: JSON.stringify({ carrier: name }) })
      setCarriers(prev => [...prev, name].sort())
      toast.success(`Carrier "${name}" ajouté`)
    } catch (e) {
      setCarriers(prev => [...prev, name].sort())
    }
  }

  const handleCreate = async () => {
    if (!validate()) return
    setActionLoading(true)
    try {
      const payload = { ...form }
      Object.keys(payload).forEach(k => { if (payload[k] === '') payload[k] = null })
      if (payload.volume_booked)    payload.volume_booked    = +payload.volume_booked
      if (payload.confirmed_volume) payload.confirmed_volume = +payload.confirmed_volume
      if (payload.charged_volume)   payload.charged_volume   = +payload.charged_volume
      if (payload.transit_time)     payload.transit_time     = +payload.transit_time
      await apiFetch('/shipments/', { method: 'POST', body: JSON.stringify(payload) })
      toast.success('Shipment créé avec succès')
      setCreateOpen(false)
      setForm(emptyForm())
      setErrors({})
      load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setActionLoading(false)
    }
  }

  const handleEdit = async () => {
    if (!validate()) return
    setActionLoading(true)
    try {
      const payload = { ...form }
      Object.keys(payload).forEach(k => { if (payload[k] === '') payload[k] = null })
      await apiFetch(`/shipments/${editTarget.id}`, { method: 'PUT', body: JSON.stringify(payload) })
      toast.success('Shipment modifié')
      setEditTarget(null)
      setErrors({})
      load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setActionLoading(false)
    }
  }

  const handleDelete = async () => {
    setActionLoading(true)
    try {
      const res = await apiFetch(`/shipments/${deleteTarget.id}`, { method: 'DELETE' })
      if (res.success) {
        toast.success('Shipment supprimé')
        setDeleteTarget(null)
        load()
      } else {
        toast.error(res.message || 'Suppression impossible')
      }
    } catch (e) {
      toast.error(e.message)
    } finally {
      setActionLoading(false)
    }
  }

  // ShipmentsPage.jsx — bouton Excel shipments annulés + en cours
const handleExportExcel = async () => {
  const res = await fetch('/api/export/excel/shipments?statuts=Annulé,En cours', {
    headers: { Authorization: `Bearer ${localStorage.getItem('kpi_token')}` }
  })
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'shipments-annules-en-cours.xlsx'
  a.click()
  URL.revokeObjectURL(url)
}

  const openEdit = (s) => {
    setErrors({})
    setForm({
      carrier: s.carrier || '', vessel_nom: s.vessel_nom || '',
      port_chargement: s.port_chargement || '', port_dechargement: s.port_dechargement || '',
      pays_destination: s.pays_destination || '',
      shipment_status: s.shipment_status || 'Normal',
      etd: s.etd || '', eta: s.eta || '', atd: s.atd || '', ata: s.ata || '',
      incoterm: s.incoterm || '', volume_booked: s.volume_booked || '',
      confirmed_volume: s.confirmed_volume || '', charged_volume: s.charged_volume || '',
      transit_time: s.transit_time || '', frequency: s.frequency || '',
    })
    setEditTarget(s)
  }

  const f = (key, value) => {
    setForm(prev => ({ ...prev, [key]: value }))
    if (errors[key]) setErrors(prev => ({ ...prev, [key]: undefined }))
  }

  const columns = [
    { key: 'id', label: '#', sortable: true, render: v => <span style={{ fontSize: '11px', fontFamily: 'monospace', color: 'var(--color-text-tertiary)' }}>#{v}</span> },
    {key: 'operateur_nom', label: 'Opérateur', sortable: true, render: (_, row) => {const prenom = row.operateur_prenom || '' , nom    = row.operateur_nom    || '', full   = [prenom, nom].filter(Boolean).join(' ') 
      return <span>{full || '—'}</span>
  }
},
    { key: 'carrier', label: 'Carrier', sortable: true, render: v => <span style={{ fontWeight: 500, color: 'var(--color-text-primary)' }}>{v || '—'}</span> },
    { key: 'vessel_nom', label: 'Navire', sortable: true },
    { key: 'port_chargement', label: 'Port départ', sortable: true },
    { key: 'port_dechargement', label: 'Port arrivée', sortable: true },
    { key: 'etd', label: 'ETD', sortable: true, render: v => v ? new Date(v).toLocaleDateString('fr-FR') : '—' },
    { key: 'eta', label: 'ETA', sortable: true, render: v => v ? new Date(v).toLocaleDateString('fr-FR') : '—' },
    { key: 'shipment_status', label: 'Statut', render: v => <Badge variant={statusVariant(v)} size="sm">{v || '—'}</Badge> },
    {
      key: 'actions', label: '',
      render: (_, row) => (
        <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end' }}>
          <button onClick={e => { e.stopPropagation(); setDetailTarget(row) }} className={styles.iconBtn} title="Détail"><Eye size={13} /></button>
          {isOperateur && (
            <>
              <button onClick={e => { e.stopPropagation(); openEdit(row) }} className={styles.iconBtn} title="Modifier"><Pencil size={13} /></button>
              <button onClick={e => { e.stopPropagation(); setDeleteTarget(row) }} className={`${styles.iconBtn} ${styles.danger}`} title="Supprimer"><Trash2 size={13} /></button>
            </>
          )}
        </div>
      ),
    },
  ]

  // Compteurs pour les onglets
  const counts = {
     tous:     shipments.length,
     en_cours: shipments.filter(s => s.shipment_status === 'Normal' && !s.ata).length,
     termines: shipments.filter(s => s.shipment_status === 'Normal' && !!s.ata).length,
     annules:  shipments.filter(s => s.shipment_status === 'Cancelled').length,
     supprimes: supprimes.length, 
  }

  return (
    <AppLayout>
      <Header title="Shipments" subtitle={`${filtered.length} expéditions`}>
        <div className={styles.searchWrap}>
          <Search size={13} className={styles.searchIcon} />
          <input
            className={styles.searchInput}
            placeholder="Rechercher..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <Select value={filterCarrier} onChange={e => setFilterCarrier(e.target.value)} style={{ width: 160 }}>
          <option value="">Tous les carriers</option>
          {carriers.map(c => <option key={c} value={c}>{c}</option>)}
        </Select>
        {isOperateur && (
          <Button icon={Plus} onClick={() => { setForm(emptyForm()); setErrors({}); setCreateOpen(true) }} size="sm">Nouveau</Button>
        )}
      </Header>

      {/* ── Onglets ── juste après le Header, avant le content */}
      <div className={styles.tabs}>
        {[
          { key: 'tous',     label: 'Tous',        count: counts.tous },
          { key: 'en_cours', label: '🚢 En cours',  count: counts.en_cours },
          { key: 'termines', label: '✅ Terminés',  count: counts.termines },
          { key: 'annules',  label: '❌ Annulés',   count: counts.annules },
          { key: 'supprimes', label: '🗑️ Supprimés', count: counts.supprimes },
        ].map(tab => (
          <button
            key={tab.key}
            className={`${styles.tab} ${activeTab === tab.key ? styles.activeTab : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
            <span className={styles.tabCount}>{tab.count}</span>
          </button>
        ))}
      </div>

      {/* ── Table ── */}
      <div className={styles.content}>
        {loading
          ? <SkeletonTable rows={8} cols={8} />
          : <DataTable columns={columns} data={filtered} rowKey="id" emptyMessage="Aucun shipment trouvé" />
        }
      </div>

      {/* Create / Edit modal */}
      <Modal
        open={createOpen || !!editTarget}
        onClose={() => { setCreateOpen(false); setEditTarget(null); setErrors({}) }}
        title={editTarget ? 'Modifier le shipment' : 'Nouveau shipment'}
        size="lg"
        footer={
          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
            <Button variant="ghost" size="sm" onClick={() => { setCreateOpen(false); setEditTarget(null); setErrors({}) }}>Annuler</Button>
            <Button size="sm" onClick={editTarget ? handleEdit : handleCreate} loading={actionLoading}>
              {editTarget ? 'Enregistrer' : 'Créer'}
            </Button>
          </div>
        }
      >
        <div className={styles.formGrid}>
          <div className={styles.fieldWrap}>
            <CarrierCombobox value={form.carrier} onChange={v => f('carrier', v)} carriers={carriers} onAddCarrier={handleAddCarrier} />
            {errors.carrier && <span className={styles.fieldError}>{errors.carrier}</span>}
          </div>
          <div className={styles.fieldWrap}>
            <Input label="Navire *" value={form.vessel_nom} onChange={e => f('vessel_nom', e.target.value)} placeholder="Nom du navire" />
            {errors.vessel_nom && <span className={styles.fieldError}>{errors.vessel_nom}</span>}
          </div>
          <div className={styles.fieldWrap}>
            <Input label="Port de chargement *" value={form.port_chargement} onChange={e => f('port_chargement', e.target.value)}  />
            {errors.port_chargement && <span className={styles.fieldError}>{errors.port_chargement}</span>}
          </div>
          <div className={styles.fieldWrap}>
            <Input label="Port de déchargement *" value={form.port_dechargement} onChange={e => f('port_dechargement', e.target.value)} />
            {errors.port_dechargement && <span className={styles.fieldError}>{errors.port_dechargement}</span>}
          </div>
          <div className={styles.fieldWrap}>
            <Input label="Pays destination *" value={form.pays_destination} onChange={e => f('pays_destination', e.target.value)}  />
            {errors.pays_destination && <span className={styles.fieldError}>{errors.pays_destination}</span>}
          </div>
          <Select label="Statut" value={form.shipment_status} onChange={e => f('shipment_status', e.target.value)}>
            <option value="Normal">Normal</option>
            <option value="Cancelled">Cancelled</option>
          </Select>
          <div className={styles.fieldWrap}>
            <Input label="ETD *" type="date" value={form.etd} onChange={e => f('etd', e.target.value)} />
            {errors.etd && <span className={styles.fieldError}>{errors.etd}</span>}
          </div>
          <div className={styles.fieldWrap}>
            <Input label="ETA *" type="date" value={form.eta} onChange={e => f('eta', e.target.value)}  />
            {errors.eta && <span className={styles.fieldError}>{errors.eta}</span>}
          </div>
          <Input label="ATD" type="date" value={form.atd} onChange={e => f('atd', e.target.value)} />
          <Input label="ATA" type="date" value={form.ata} onChange={e => f('ata', e.target.value)} />
          <div className={styles.fieldWrap}>
            <Input label="Volume réservé *" type="number" min="0.001" step="any" value={form.volume_booked} onChange={e => f('volume_booked', e.target.value)}  />
            {errors.volume_booked && <span className={styles.fieldError}>{errors.volume_booked}</span>}
          </div>
          <div className={styles.fieldWrap}>
            <Input label="Volume confirmé *" type="number" min="0.001" step="any" value={form.confirmed_volume} onChange={e => f('confirmed_volume', e.target.value)} />
            {errors.confirmed_volume && <span className={styles.fieldError}>{errors.confirmed_volume}</span>}
          </div>
          <div className={styles.fieldWrap}>
            <Input label="Volume chargé " type="number" min="0.001" step="any" value={form.charged_volume} onChange={e => f('charged_volume', e.target.value)} />
            {errors.charged_volume && <span className={styles.fieldError}>{errors.charged_volume}</span>}
          </div>
          <div className={styles.fieldWrap}>
            <Input label="Transit time (jours) *" type="number" value={form.transit_time} onChange={e => f('transit_time', e.target.value)}  />
            {errors.transit_time && <span className={styles.fieldError}>{errors.transit_time}</span>}
          </div>
          <div className={styles.fieldWrap}>
            <Select label="Incoterm *" value={form.incoterm} onChange={e => f('incoterm', e.target.value)} error={errors.incoterm}>
              <option value="">—</option>
              {INCOTERMS.map(i => <option key={i} value={i}>{i}</option>)}
            </Select>
            {errors.incoterm && <span className={styles.fieldError}>{errors.incoterm}</span>}
          </div>
          <div className={styles.fieldWrap}>
            <Input label="Fréquence *" value={form.frequency} onChange={e => f('frequency', e.target.value)} placeholder="ex: 7j, 14j, 30j"  />
            {errors.frequency && <span className={styles.fieldError}>{errors.frequency}</span>}
            <span className={styles.fieldHint}>Format requis : nombre suivi de "j" — ex: 7j</span>
          </div>
        </div>
      </Modal>

      {/* Delete confirm */}
      <ConfirmModal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="Supprimer le shipment"
        message={`Confirmer la suppression du shipment #${deleteTarget?.id} (${deleteTarget?.carrier} — ${deleteTarget?.vessel_nom}) ?`}
        confirmLabel="Supprimer"
        danger
        loading={actionLoading}
      />

      {/* Detail modal */}
      {detailTarget && (
        <Modal open={!!detailTarget} onClose={() => setDetailTarget(null)} title={`Shipment #${detailTarget.id} — Données calculées`} size="lg">
          <div className={styles.detailGrid}>
            <div className={styles.detailSectionHeader}>Données additionnelles</div>
            <div className={styles.detailSectionHeader} />
            {[
              ['Transit time', detailTarget.transit_time != null ? `${detailTarget.transit_time} j` : null],
              ['Incoterm',        detailTarget.incoterm],
              ['Fréquence',       detailTarget.frequency],
              ['Type annulation', detailTarget.type_annulation],
              ['ATD', detailTarget.atd ? new Date(detailTarget.atd).toLocaleDateString('fr-FR') : null],
              ['ATA', detailTarget.ata ? new Date(detailTarget.ata).toLocaleDateString('fr-FR') : null],
            ].map(([label, value]) => (
              <div key={label} className={styles.detailItem}>
                <span className={styles.detailLabel}>{label}</span>
                <span className={styles.detailValue}>{value || '—'}</span>
              </div>
            ))}
            <div className={styles.detailDivider} />
            <div className={styles.detailDivider} />
            <div className={styles.detailSectionHeader}>Colonnes dérivées (calculées automatiquement)</div>
            <div className={styles.detailSectionHeader} />
            {[
              ['Mois', detailTarget.month],
              ['Année', detailTarget.year],
              ['Transit time réel',        detailTarget.transit_time_reel != null ? `${detailTarget.transit_time_reel} j` : null],
              ['ETA déviation',            detailTarget.eta_deviation != null ? `${detailTarget.eta_deviation} j` : null],
              ['ETD déviation',            detailTarget.etd_deviation != null ? `${detailTarget.etd_deviation} j` : null],
              ['Ratio chargé / confirmé',  detailTarget.volume_ratio_loaded != null ? `${(detailTarget.volume_ratio_loaded * 100).toFixed(1)} %` : null],
              ['Ratio confirmé / réservé', detailTarget.volume_ratio_allocated_booked != null ? `${(detailTarget.volume_ratio_allocated_booked * 100).toFixed(1)} %` : null],
              ['Niveau de retard',         detailTarget.niveau_retard],
            ].map(([label, value]) => (
              <div key={label} className={styles.detailItem}>
                <span className={styles.detailLabel}>{label}</span>
                <span className={styles.detailValue}>{value || '—'}</span>
              </div>
            ))}
                        <div className={styles.detailDivider} />
            <div className={styles.detailDivider} />
            <div className={styles.detailSectionHeader}>Traçabilité</div>
            <div className={styles.detailSectionHeader} />
            {[
              ['Créé le',        detailTarget.created_at
                ? new Date(detailTarget.created_at).toLocaleString('fr-FR')
                : null],
              ['Modifié le',     detailTarget.updated_at
                ? new Date(detailTarget.updated_at).toLocaleString('fr-FR')
                : null],
              ['Modifié par', detailTarget.modificateur_prenom
  ? `${detailTarget.modificateur_prenom} ${detailTarget.modificateur_nom}`
  : null],
              ['Supprimé le',  detailTarget.deleted_at
  ? new Date(detailTarget.deleted_at).toLocaleString('fr-FR')
  : null],
['Supprimé par', detailTarget.suppresseur_prenom
  ? `${detailTarget.suppresseur_prenom} ${detailTarget.suppresseur_nom}`
  : null],
            ].map(([label, value]) => (
              <div key={label} className={styles.detailItem}>
                <span className={styles.detailLabel}>{label}</span>
                <span className={styles.detailValue}>{value || '—'}</span>
              </div>
            ))}
          </div>
          <p className={styles.detailNote}>
            💡 Les données principales (carrier, navire, ports, volumes, dates) sont visibles dans le tableau.
            Ce panneau affiche uniquement les données calculées automatiquement par l&apos;ETL.
          </p>
        </Modal>
      )}
    </AppLayout>
  )
}