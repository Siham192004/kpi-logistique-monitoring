import React from 'react'
import clsx from 'clsx'

export const Skeleton = ({ className, style }) => (
  <div className={clsx('skeleton', className)} style={style} />
)

export const SkeletonKPICard = () => (
  <div style={{
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius-lg)',
    padding: '20px',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
      <Skeleton style={{ width: '80px', height: '11px', borderRadius: '4px' }} />
      <Skeleton style={{ width: '28px', height: '28px', borderRadius: '8px' }} />
    </div>
    <Skeleton style={{ width: '120px', height: '32px', borderRadius: '6px' }} />
    <Skeleton style={{ width: '160px', height: '11px', borderRadius: '4px' }} />
    <div style={{ display: 'flex', gap: '8px' }}>
      <Skeleton style={{ width: '80px', height: '22px', borderRadius: '999px' }} />
      <Skeleton style={{ width: '60px', height: '22px', borderRadius: '999px' }} />
    </div>
  </div>
)

export const SkeletonTable = ({ rows = 5, cols = 5 }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
    {/* Header */}
    <div style={{
      display: 'grid',
      gridTemplateColumns: `repeat(${cols}, 1fr)`,
      gap: '12px',
      padding: '12px 16px',
      background: 'var(--color-surface-2)',
      borderRadius: 'var(--radius-md) var(--radius-md) 0 0',
    }}>
      {Array.from({ length: cols }).map((_, i) => (
        <Skeleton key={i} style={{ height: '11px', borderRadius: '4px', opacity: 0.7 }} />
      ))}
    </div>
    {/* Rows */}
    {Array.from({ length: rows }).map((_, ri) => (
      <div key={ri} style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${cols}, 1fr)`,
        gap: '12px',
        padding: '14px 16px',
        background: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-border)',
      }}>
        {Array.from({ length: cols }).map((_, ci) => (
          <Skeleton key={ci} style={{ height: '11px', borderRadius: '4px', width: `${60 + Math.random() * 40}%` }} />
        ))}
      </div>
    ))}
  </div>
)

export const SkeletonChart = ({ height = 200 }) => (
  <div style={{
    height,
    background: 'var(--color-surface-2)',
    borderRadius: 'var(--radius-md)',
    display: 'flex',
    alignItems: 'flex-end',
    padding: '16px',
    gap: '8px',
  }}>
    {Array.from({ length: 8 }).map((_, i) => (
      <Skeleton
        key={i}
        style={{
          flex: 1,
          height: `${30 + Math.random() * 70}%`,
          borderRadius: '4px 4px 0 0',
        }}
      />
    ))}
  </div>
)
