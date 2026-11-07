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
      downloadReport: (request: { path: string; filename?: string }) => Promise<{ status: 'saved' | 'cancelled' | 'error'; message?: string }>
      saveProjectContract: (projectId: string, filename: string) => Promise<{ status: 'saved' | 'cancelled' | 'error'; message?: string }>
      readSpreadsheet: () => Promise<{ status: 'selected' | 'cancelled' | 'error'; message?: string; file_name?: string; content_base64?: string }>
      exportBackup: (backupId: string) => Promise<{ status: 'saved' | 'cancelled' | 'error'; message?: string }>
      importBackup: () => Promise<{ status: 'imported' | 'cancelled' | 'error'; backupId?: string; message?: string }>
    }
    app: {
      getInfo: () => Promise<import('./lib/types').DesktopInfo>
      getUpdateState: () => Promise<import('./lib/types').UpdateState>
      checkForUpdates: () => Promise<import('./lib/types').UpdateState>
      downloadUpdate: () => Promise<import('./lib/types').UpdateState>
      installUpdate: () => Promise<{ accepted: boolean }>
      relaunch: () => Promise<{ accepted: boolean }>
      toggleProjectBar: () => Promise<{ visible: boolean }>
      hideProjectBar: () => Promise<{ visible: boolean }>
      takePendingRoute: () => Promise<string | null>
      notifyDataChanged: () => void
      onDataChanged: (callback: () => void) => () => void
      setProjectBarExpanded: (expanded: boolean) => Promise<{ accepted: boolean }>
      showMain: (projectId?: string) => Promise<{ accepted: boolean }>
      onNavigate: (callback: (route: string) => void) => () => void
    }
  }
}
