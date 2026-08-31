import React from 'react'
import clsx from 'clsx'
import styles from './Input.module.css'

export const Input = React.forwardRef(({
  label,
  error,
  hint,
  icon: Icon,
  className,
  ...props
}, ref) => (
  <div className={styles.wrapper}>
    {label && <label className={styles.label}>{label}</label>}
    <div className={styles.inputWrap}>
      {Icon && <Icon size={14} className={styles.icon} />}
      <input
        ref={ref}
        className={clsx(styles.input, Icon && styles.withIcon, error && styles.hasError, className)}
        {...props}
      />
    </div>
    {error && <p className={styles.error}>{error}</p>}
    {hint && !error && <p className={styles.hint}>{hint}</p>}
  </div>
))
Input.displayName = 'Input'

export const Select = React.forwardRef(({
  label,
  error,
  children,
  className,
  ...props
}, ref) => (
  <div className={styles.wrapper}>
    {label && <label className={styles.label}>{label}</label>}
    <div className={styles.inputWrap}>
      <select
        ref={ref}
        className={clsx(styles.input, styles.select, error && styles.hasError, className)}
        {...props}
      >
        {children}
      </select>
    </div>
    {error && <p className={styles.error}>{error}</p>}
  </div>
))
Select.displayName = 'Select'

export const Textarea = React.forwardRef(({
  label, error, className, ...props
}, ref) => (
  <div className={styles.wrapper}>
    {label && <label className={styles.label}>{label}</label>}
    <textarea
      ref={ref}
      className={clsx(styles.input, styles.textarea, error && styles.hasError, className)}
      {...props}
    />
    {error && <p className={styles.error}>{error}</p>}
  </div>
))
Textarea.displayName = 'Textarea'
