const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('rlbDesktop', {
  platform: process.platform,
  runtimeUrl: 'http://127.0.0.1:8000',
  getLocalApiToken: () => ipcRenderer.invoke('get-local-api-token'),
  selectLocalFolder: () => ipcRenderer.invoke('select-local-folder'),
  pairDevice: (request) => ipcRenderer.invoke('pair-device', request),
});
