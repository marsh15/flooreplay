import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/600.css'
import './index.css'

import App from './App.tsx'
import { AuthProvider } from '@/components/Auth'

const queryClient = new QueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider><BrowserRouter>
        <App />
      </BrowserRouter></AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
