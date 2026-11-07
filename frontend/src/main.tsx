import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App.tsx'
import '@fontsource-variable/geist'
import '@fontsource-variable/geist-mono'
import './index.css'
import './brutalist.css'

const queryClient = new QueryClient({
  // Bir pencerede kayıt değişince diğer pencere (ana pencere ↔ mini bar) önbelleğini yeniler.
  mutationCache: new MutationCache({ onSuccess: () => window.ksDesktop?.app.notifyDataChanged?.() }),
  defaultOptions: {
    queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false },
    mutations: { retry: false },
  },
})

window.ksDesktop?.app.onDataChanged?.(() => { void queryClient.invalidateQueries() })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}><App /></QueryClientProvider>
  </StrictMode>,
)
