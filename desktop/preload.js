const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('rlbDesktop', {
  platform: process.platform,
  getRuntimeUrl: () => ipcRenderer.invoke('get-runtime-url'),
  getLocalIdentity: () => ipcRenderer.invoke('get-local-identity'),
  getLocalApiToken: () => ipcRenderer.invoke('get-local-api-token'),
  selectLocalFolder: () => ipcRenderer.invoke('select-local-folder'),
  pairDevice: (request) => ipcRenderer.invoke('pair-device', request),
});
