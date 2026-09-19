import React, { useState, useEffect, useRef, useCallback } from 'react'
import { AppLayout } from '../components/layout/AppLayout'
import { Header } from '../components/layout/Header'
import { Button } from '../components/ui/Button'
import { Select, Textarea } from '../components/ui/Input'
import { Modal } from '../components/ui/Modal'
import { apiFetch, useAuthStore } from '../store/auth'
import { Send, MessageSquare, Plus, RefreshCw, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import styles from './MessagesPage.module.css'

const formatDate = (d) => {
  if (!d) return ''
  const date = new Date(d.endsWith('Z') ? d : d + 'Z')
  const now   = new Date()
  const diff  = now - date
  if (diff < 60000)    return "À l'instant"
  if (diff < 3600000)  return `${Math.floor(diff / 60000)} min`
  const isToday     = date.toDateString() === now.toDateString()
  const yesterday   = new Date(now); yesterday.setDate(now.getDate() - 1)
  const isYesterday = date.toDateString() === yesterday.toDateString()
  const time = date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  if (isToday)     return time
  if (isYesterday) return `Hier ${time}`
  return date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) + ` ${time}`
}

const formatDateSeparator = (d) => {
  if (!d) return ''
  const date = new Date(d.endsWith('Z') ? d : d + 'Z')
  const now  = new Date()
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1)
  if (date.toDateString() === now.toDateString())        return "Aujourd'hui"
  if (date.toDateString() === yesterday.toDateString())  return 'Hier'
  return date.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
}

export const MessagesPage = () => {
  const user = useAuthStore(state => state.user)

  const [conversations, setConversations] = useState([])
  const [destinataires, setDestinataires] = useState([])
  const [activeConv, setActiveConv]       = useState(null)
  const [messages, setMessages]           = useState([])
  const [newText, setNewText]             = useState('')
  const [sending, setSending]             = useState(false)
  const [composeOpen, setComposeOpen]     = useState(false)
  const [composeForm, setComposeForm]     = useState({ destinataire_id: '', contenu: '' })
  const badge                             = useAuthStore(state => state.msgBadge)
  const [loadingConvs, setLoadingConvs]   = useState(true)
  const [hoveredMsg, setHoveredMsg]       = useState(null)
  const [deletingId, setDeletingId]       = useState(null)

  const messagesEndRef = useRef(null)
  const activeConvRef  = useRef(null)

  useEffect(() => { activeConvRef.current = activeConv }, [activeConv])

  const loadConversations = useCallback(async (silent = false) => {
    if (!silent) setLoadingConvs(true)
    try {
      const currentUserId = useAuthStore.getState().user?.id
      const [convData, dests, b] = await Promise.all([
        apiFetch('/messages/'),
        apiFetch('/messages/destinataires'),
        apiFetch('/messages/badge'),
      ])
      const msgs    = convData.messages ?? convData ?? []
      const convMap = {}
      msgs.forEach(msg => {
        const isMine  = msg.expediteur_id === currentUserId
        const autreId = isMine ? msg.destinataire_id : msg.expediteur_id
        if (!autreId || autreId === currentUserId) return
        const autrePrenom = isMine ? msg.destinataire_prenom : msg.expediteur_prenom
        const autreNom    = isMine ? msg.destinataire_nom    : msg.expediteur_nom
        const cle         = [currentUserId, autreId].sort((a, b) => a - b).join('-')
        if (!convMap[cle]) {
          convMap[cle] = {
            autre_user_id:        autreId,
            autre_prenom:         autrePrenom ?? '?',
            autre_nom:            autreNom    ?? '',
            dernier_message:      msg.contenu,
            dernier_message_date: msg.date_envoi,
            non_lus:              0,
          }
        } else {
          if (new Date(msg.date_envoi) > new Date(convMap[cle].dernier_message_date)) {
            convMap[cle].dernier_message      = msg.contenu
            convMap[cle].dernier_message_date = msg.date_envoi
          }
        }
        if (!isMine && !msg.lu) convMap[cle].non_lus++
      })
      const convList = Object.values(convMap).sort(
        (a, b) => new Date(b.dernier_message_date) - new Date(a.dernier_message_date)
      )
      setConversations(convList)
      setDestinataires(
        Array.isArray(dests)                ? dests :
        Array.isArray(dests?.items)         ? dests.items :
        Array.isArray(dests?.destinataires) ? dests.destinataires :
        []
      )
    } catch (e) {}
    finally { setLoadingConvs(false) }
  }, [])

  const loadMessages = useCallback(async (autreUserId) => {
    if (!autreUserId) return
    try {
      const result = await apiFetch(`/messages/conversation/${autreUserId}`)
      const msgs   = result.messages ?? result ?? []
      setMessages(msgs)
    } catch (e) {}
  }, [])

  useEffect(() => {
    loadConversations()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const openConversation = async (conv) => {
    setActiveConv(conv)
    setConversations(prev =>
      prev.map(c => c.autre_user_id === conv.autre_user_id ? { ...c, non_lus: 0 } : c)
    )
    await loadMessages(conv.autre_user_id)
    try {
      await apiFetch(`/messages/conversation/${conv.autre_user_id}/lu`, { method: 'PUT' })
    } catch (e) {}
  }

  const handleSend = async () => {
    if (!newText.trim() || !activeConv) return
    setSending(true)
    const texte = newText.trim()
    setNewText('')
    try {
      await apiFetch('/messages/', {
        method: 'POST',
        body: JSON.stringify({ destinataire_id: activeConv.autre_user_id, contenu: texte }),
      })
      await loadMessages(activeConv.autre_user_id)
      await loadConversations(true)
    } catch (e) {
      toast.error('Envoi échoué')
      setNewText(texte)
    } finally {
      setSending(false)
    }
  }

  useEffect(() => {
    const handleNouveauMessage = async () => {
        // Recharger les conversations
        await loadConversations(true)
        // Si une conversation est ouverte, recharger les messages
        if (activeConvRef.current?.autre_user_id) {
            await loadMessages(activeConvRef.current.autre_user_id)
        }
    }

    window.addEventListener('nouveau_message', handleNouveauMessage)
    return () => window.removeEventListener('nouveau_message', handleNouveauMessage)
}, [loadConversations, loadMessages])

  const handleDelete = async (msgId) => {
    setDeletingId(msgId)
    try {
      await apiFetch(`/messages/${msgId}`, { method: 'DELETE' })
      setMessages(prev => prev.filter(m => m.id !== msgId))
      await loadConversations(true)
      toast.success('Message supprimé')
    } catch (e) {
      toast.error('Suppression échouée')
    } finally {
      setDeletingId(null)
      setHoveredMsg(null)
    }
  }

  const handleCompose = async () => {
    if (!composeForm.destinataire_id || !composeForm.contenu.trim()) return
    setSending(true)
    try {
      await apiFetch('/messages/', {
        method: 'POST',
        body: JSON.stringify({
          destinataire_id: +composeForm.destinataire_id,
          contenu: composeForm.contenu.trim(),
        }),
      })
      toast.success('Message envoyé')
      setComposeOpen(false)
      setComposeForm({ destinataire_id: '', contenu: '' })
      await loadConversations()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSending(false)
    }
  }

  const groupedMessages = () => {
    const groups = []
    let lastDate = null
    messages.forEach((msg, i) => {
      const d = msg.date_envoi ? new Date(msg.date_envoi.endsWith('Z') ? msg.date_envoi : msg.date_envoi + 'Z') : null
      const dateStr = d ? d.toDateString() : null
      if (dateStr && dateStr !== lastDate) {
        groups.push({ type: 'separator', label: formatDateSeparator(msg.date_envoi), key: `sep-${i}` })
        lastDate = dateStr
      }
      groups.push({ type: 'msg', msg, key: msg.id ?? i })
    })
    return groups
  }

  const currentUserId = user?.id

  return (
    <AppLayout>
      <Header title="Messagerie" subtitle="Communications internes">
        {badge > 0 && (
          <span className={styles.badgePill}>{badge} non lu{badge > 1 ? 's' : ''}</span>
        )}
        <button className={styles.refreshBtn} onClick={() => loadConversations()} title="Actualiser">
          <RefreshCw size={13} className={loadingConvs ? styles.spinning : ''} />
        </button>
        <Button size="sm" icon={Plus} onClick={() => setComposeOpen(true)}>Nouveau</Button>
      </Header>

      <div className={styles.layout}>

        {/* ── Liste des conversations ── */}
        <div className={styles.convList}>
          <div className={styles.convListHeader}>
            <span className={styles.convListTitle}>Conversations</span>
            <span className={styles.convCount}>{conversations.length}</span>
          </div>

          {loadingConvs && conversations.length === 0 ? (
            <div className={styles.emptyConv}>
              <div className={styles.convSkeleton} />
              <div className={styles.convSkeleton} />
              <div className={styles.convSkeleton} />
            </div>
          ) : conversations.length === 0 ? (
            <div className={styles.emptyConv}>
              <MessageSquare size={24} />
              <p>Aucune conversation</p>
              <p style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 4 }}>
                Cliquez sur "Nouveau" pour démarrer
              </p>
            </div>
          ) : (
            conversations.map(conv => {
              return (
                <button
                  key={conv.autre_user_id}
                  className={`${styles.convItem} ${activeConv?.autre_user_id === conv.autre_user_id ? styles.activeConv : ''}`}
                  onClick={() => openConversation(conv)}
                >
                  <div className={styles.convInfo}>
                    <div className={styles.convName}>
                      {/* ✅ Nom + statut texte */}
                      <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                        {conv.autre_prenom} {conv.autre_nom}
                      </span>
                      <span className={styles.convTime}>{formatDate(conv.dernier_message_date)}</span>
                    </div>
                    <p className={styles.convPreview}>{conv.dernier_message || 'Aucun message'}</p>
                    {conv.non_lus > 0 && (
                      <span className={styles.unreadCount}>{conv.non_lus}</span>
                    )}
                  </div>
                </button>
              )
            })
          )}
        </div>

        {/* ── Zone de chat ── */}
        <div className={styles.chatArea}>
          {!activeConv ? (
            <div className={styles.chatEmpty}>
              <div className={styles.chatEmptyIcon}><MessageSquare size={32} /></div>
              <p className={styles.chatEmptyTitle}>Sélectionnez une conversation</p>
              <p className={styles.chatEmptySub}>ou démarrez une nouvelle discussion</p>
              <Button size="sm" icon={Plus} onClick={() => setComposeOpen(true)}>
                Nouvelle conversation
              </Button>
            </div>
          ) : (
            <>
              {/* ✅ Header avec présence */}
              <div className={styles.chatHeader}>
                <div style={{ position: 'relative', display: 'inline-flex' }}>
                  <div className={styles.chatAvatar}>
                    {activeConv.autre_prenom?.[0]}{activeConv.autre_nom?.[0]}
                  </div>
                
                </div>
                <div>
                  <p className={styles.chatName}>{activeConv.autre_prenom} {activeConv.autre_nom}</p>
  
                </div>
              </div>

              <div className={styles.messages}>
                {messages.length === 0 ? (
                  <div className={styles.noMessages}>
                    <p>Aucun message — commencez la conversation !</p>
                  </div>
                ) : (
                  groupedMessages().map((item, i) => {
                    if (item.type === 'separator') {
                      return (
                        <div key={item.key} className={styles.dateSeparator}>
                          <span className={styles.dateSeparatorLabel}>{item.label}</span>
                        </div>
                      )
                    }
                    const msg    = item.msg
                    const isMine = msg.expediteur_id === currentUserId
                    return (
                      <div
                        key={item.key}
                        className={`${styles.msg} ${isMine ? styles.msgMine : styles.msgOther}`}
                        style={{ animationDelay: `${Math.min(i, 10) * 20}ms` }}
                        onMouseEnter={() => setHoveredMsg(msg.id)}
                        onMouseLeave={() => setHoveredMsg(null)}
                      >
                        {isMine && hoveredMsg === msg.id && (
                          <button
                            className={styles.deleteBtn}
                            onClick={() => handleDelete(msg.id)}
                            disabled={deletingId === msg.id}
                            title="Supprimer"
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                        <div className={styles.msgBubble}>
                          <p className={styles.msgText}>{msg.contenu}</p>
                          <span className={styles.msgTime}>{formatDate(msg.date_envoi)}</span>
                        </div>
                      </div>
                    )
                  })
                )}
                <div ref={messagesEndRef} />
              </div>

              <div className={styles.chatInput}>
                <input
                  className={styles.messageInput}
                  placeholder="Écrire un message... (Entrée pour envoyer)"
                  value={newText}
                  onChange={e => setNewText(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
                  }}
                  autoFocus
                />
                <Button size="sm" icon={Send} onClick={handleSend} loading={sending} disabled={!newText.trim()}>
                  Envoyer
                </Button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Modal nouveau message */}
      <Modal
        open={composeOpen}
        onClose={() => setComposeOpen(false)}
        title="Nouveau message"
        size="sm"
        footer={
          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
            <Button variant="ghost" size="sm" onClick={() => setComposeOpen(false)}>Annuler</Button>
            <Button size="sm" icon={Send} onClick={handleCompose} loading={sending}>Envoyer</Button>
          </div>
        }
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <Select
            label="Destinataire"
            value={composeForm.destinataire_id}
            onChange={e => setComposeForm({ ...composeForm, destinataire_id: e.target.value })}
          >
            <option value="">Sélectionner un destinataire</option>
            {/* ✅ Point de présence dans le select du modal */}
            {destinataires.map(d => (
              <option key={d.id} value={d.id}>

              </option>
            ))}
          </Select>
          <Textarea
            label="Message"
            rows={4}
            placeholder="Votre message..."
            value={composeForm.contenu}
            onChange={e => setComposeForm({ ...composeForm, contenu: e.target.value })}
          />
        </div>
      </Modal>
    </AppLayout>
  )
}