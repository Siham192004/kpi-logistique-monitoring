import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './styles/globals.css'
import { Toaster } from 'react-hot-toast'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: 'var(--color-surface-2)',
            color: 'var(--color-text-primary)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            fontSize: '13px',
            fontFamily: 'Inter, system-ui, sans-serif',
            boxShadow: 'var(--shadow-lg)',
          },
          success: {
            iconTheme: { primary: 'var(--color-success)', secondary: 'transparent' },
          },
          error: {
            iconTheme: { primary: 'var(--color-danger)', secondary: 'transparent' },
          },
          duration: 3500,
        }}
      />
    </BrowserRouter>
  </React.StrictMode>
)
