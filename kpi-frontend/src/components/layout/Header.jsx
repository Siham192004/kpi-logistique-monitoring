import React from 'react'
import { Menu } from 'lucide-react'
import { useSidebar } from './SidebarContext'
import styles from './Header.module.css'

export const Header = ({ title, subtitle, actions, children }) => {
  const { setMobileOpen } = useSidebar()

  return (
    <header className={styles.header}>
      <div className={styles.left}>
        <button
          className={styles.menuBtn}
          onClick={() => setMobileOpen(o => !o)}
          aria-label="Ouvrir le menu"
        >
          <Menu size={18} />
        </button>
        <div>
          <h1 className={styles.title}>{title}</h1>
          {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
        </div>
      </div>

      <div className={styles.right}>
        {children}
        {actions}
      </div>
    </header>
  )
}
