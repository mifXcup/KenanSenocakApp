const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('ksDesktop', {
  api: {
    request: (request) => ipcRenderer.invoke('api:request', request),
    downloadReport: (request) => ipcRenderer.invoke('api:download', request),
    saveProjectContract: (projectId, filename) => ipcRenderer.invoke('api:save-project-contract', { projectId, filename }),
    readSpreadsheet: () => ipcRenderer.invoke('api:read-spreadsheet'),
    exportBackup: (backupId) => ipcRenderer.invoke('backup:export', backupId),
    importBackup: () => ipcRenderer.invoke('backup:import'),
  },
  app: {
    getInfo: () => ipcRenderer.invoke('app:get-info'),
    getUpdateState: () => ipcRenderer.invoke('app:get-update-state'),
    checkForUpdates: () => ipcRenderer.invoke('app:check-for-updates'),
    downloadUpdate: () => ipcRenderer.invoke('app:download-update'),
    installUpdate: () => ipcRenderer.invoke('app:install-update'),
    relaunch: () => ipcRenderer.invoke('app:relaunch'),
    toggleProjectBar: () => ipcRenderer.invoke('app:toggle-project-bar'),
    hideProjectBar: () => ipcRenderer.invoke('app:hide-project-bar'),
    takePendingRoute: () => ipcRenderer.invoke('app:take-pending-route'),
    notifyDataChanged: () => ipcRenderer.send('app:data-changed'),
    onDataChanged: (callback) => {
      const handler = () => callback()
      ipcRenderer.on('app:data-changed', handler)
      return () => ipcRenderer.removeListener('app:data-changed', handler)
    },
    setProjectBarExpanded: (expanded) => ipcRenderer.invoke('app:set-project-bar-expanded', Boolean(expanded)),
    showMain: (projectId) => ipcRenderer.invoke('app:show-main', projectId),
    onNavigate: (callback) => {
      const handler = (_event, route) => callback(route)
      ipcRenderer.on('app:navigate', handler)
      return () => ipcRenderer.removeListener('app:navigate', handler)
    },
  },
})
