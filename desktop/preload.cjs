const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('ksDesktop', {
  api: {
    request: (request) => ipcRenderer.invoke('api:request', request),
  },
  app: {
    getInfo: () => ipcRenderer.invoke('app:get-info'),
    relaunch: () => ipcRenderer.invoke('app:relaunch'),
    toggleProjectBar: () => ipcRenderer.invoke('app:toggle-project-bar'),
    setProjectBarExpanded: (expanded) => ipcRenderer.invoke('app:set-project-bar-expanded', Boolean(expanded)),
    showMain: (projectId) => ipcRenderer.invoke('app:show-main', projectId),
    onNavigate: (callback) => {
      const handler = (_event, route) => callback(route)
      ipcRenderer.on('app:navigate', handler)
      return () => ipcRenderer.removeListener('app:navigate', handler)
    },
  },
})
