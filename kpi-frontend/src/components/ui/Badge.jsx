import React from 'react'
import clsx from 'clsx'

/**
 * Badge — Status pill for KPI levels and counts.
 */
export const Badge = ({ children, variant = 'default', size = 'md', dot = false, className }) => {
  const variants = {
    default:    'bg-[rgba(255,255,255,0.06)] text-[rgba(255,255,255,0.6)]',
    accent:     'bg-[rgba(59,130,246,0.12)] text-[#3b82f6] border-[rgba(59,130,246,0.2)]',
    success:    'bg-[rgba(16,185,129,0.12)] text-[#10b981] border-[rgba(16,185,129,0.2)]',
    warning:    'bg-[rgba(245,158,11,0.12)] text-[#f59e0b] border-[rgba(245,158,11,0.2)]',
    danger:     'bg-[rgba(239,68,68,0.12)]  text-[#ef4444] border-[rgba(239,68,68,0.2)]',
    'on-target': 'bg-[rgba(16,185,129,0.12)] text-[#10b981] border-[rgba(16,185,129,0.2)]',
    'to-monitor':'bg-[rgba(245,158,11,0.12)] text-[#f59e0b] border-[rgba(245,158,11,0.2)]',
    critical:   'bg-[rgba(239,68,68,0.12)]  text-[#ef4444] border-[rgba(239,68,68,0.2)]',
  }

  const sizes = {
    sm: 'px-1.5 py-0.5 text-[10px]',
    md: 'px-2 py-0.5 text-[11px]',
    lg: 'px-3 py-1 text-[12px]',
  }

  const dotColors = {
    default: 'bg-[rgba(255,255,255,0.4)]',
    accent:  'bg-[#3b82f6]',
    success: 'bg-[#10b981]',
    warning: 'bg-[#f59e0b]',
    danger:  'bg-[#ef4444]',
    'on-target':  'bg-[#10b981]',
    'to-monitor': 'bg-[#f59e0b]',
    critical:     'bg-[#ef4444]',
  }

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 font-medium rounded-full border border-transparent leading-none',
        variants[variant] || variants.default,
        sizes[size],
        className
      )}
    >
      {dot && (
        <span
          className={clsx(
            'w-1.5 h-1.5 rounded-full',
            dotColors[variant] || dotColors.default
          )}
          style={{ animation: 'pulse-dot 2s ease-in-out infinite' }}
        />
      )}
      {children}
    </span>
  )
}

/** Maps API niveau string → Badge variant */
export const niveauToBadge = (niveau) => {
  if (!niveau) return 'default'
  const n = niveau.toLowerCase()
  if (n.includes('target')) return 'on-target'
  if (n.includes('monitor')) return 'to-monitor'
  if (n.includes('critical')) return 'critical'
  return 'default'
}

export const niveauLabel = (niveau) => {
  if (!niveau) return '—'
  const n = niveau.toLowerCase()
  if (n.includes('target'))  return 'On target'
  if (n.includes('monitor')) return 'À surveiller'
  if (n.includes('critical')) return 'Critique'
  return niveau
}
