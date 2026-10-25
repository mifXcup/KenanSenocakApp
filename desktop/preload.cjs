const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('ksDesktop', {
  api: {
    request: (request) => ipcRenderer.invoke('api:request', request),
  },
  app: {
    getInfo: () => ipcRenderer.invoke('app:get-info'),
    relaunch: () => ipcRenderer.invoke('app:relaunch'),
  },
})
