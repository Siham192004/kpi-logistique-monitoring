import React from 'react'
import clsx from 'clsx'
import { Loader2 } from 'lucide-react'
import styles from './Button.module.css'

/**
 * Button — Primary interactive component.
 * Variants: primary | secondary | ghost | danger
 * Sizes: sm | md | lg
 */
export const Button = React.forwardRef(({
  children,
  variant = 'primary',
  size = 'md',
  loading = false,
  icon: Icon,
  iconPosition = 'left',
  fullWidth = false,
  disabled,
  className,
  ...props
}, ref) => {
  const isDisabled = disabled || loading

  return (
    <button
      ref={ref}
      disabled={isDisabled}
      className={clsx(
        styles.btn,
        styles[variant],
        styles[size],
        fullWidth && styles.fullWidth,
        className
      )}
      {...props}
    >
      {loading && <Loader2 size={14} className={styles.spinner} />}
      {!loading && Icon && iconPosition === 'left' && <Icon size={14} className={styles.icon} />}
      {children && <span>{children}</span>}
      {!loading && Icon && iconPosition === 'right' && <Icon size={14} className={styles.icon} />}
    </button>
  )
})

Button.displayName = 'Button'
