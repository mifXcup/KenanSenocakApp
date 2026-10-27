/// <reference types="vite/client" />

interface DesktopApiResponse<T = unknown> {
  ok: boolean
  status: number
  data: T
}

interface Window {
  ksDesktop?: {
    api: {
      request: <T>(request: { path: string; method?: string; body?: unknown }) => Promise<DesktopApiResponse<T>>
    }
    app: {
      getInfo: () => Promise<import('./lib/types').DesktopInfo>
      relaunch: () => Promise<{ accepted: boolean }>
      toggleProjectBar: () => Promise<{ visible: boolean }>
      setProjectBarExpanded: (expanded: boolean) => Promise<{ accepted: boolean }>
      showMain: (projectId?: string) => Promise<{ accepted: boolean }>
      onNavigate: (callback: (route: string) => void) => () => void
    }
  }
}
