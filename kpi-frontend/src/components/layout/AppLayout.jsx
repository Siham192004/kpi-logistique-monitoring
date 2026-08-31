import React from 'react'
import { Sidebar } from './Sidebar'
import { SidebarProvider, useSidebar } from './SidebarContext'
import styles from './AppLayout.module.css'

const AppLayoutInner = ({ children }) => {
  const { collapsed } = useSidebar()
  return (
    <div className={styles.layout}>
      <Sidebar />
      <div
        className={styles.main}
        style={{
          marginLeft: collapsed ? 'var(--sidebar-collapsed)' : 'var(--sidebar-width)',
        }}
      >
        {children}
      </div>
    </div>
  )
}

export const AppLayout = ({ children }) => (
  <SidebarProvider>
    <AppLayoutInner>{children}</AppLayoutInner>
  </SidebarProvider>
)