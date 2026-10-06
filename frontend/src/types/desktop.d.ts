export {};

declare global {
  interface Window {
    rlbDesktop?: {
      platform: string;
      getRuntimeUrl: () => Promise<string>;
      getLocalIdentity: () => Promise<{ userId: string } | null>;
      getLocalApiToken: () => Promise<string>;
      selectLocalFolder: () => Promise<string | null>;
      pairDevice: (request: {
        controlPlaneUrl: string;
        pairingToken: string;
        name: string;
      }) => Promise<{ id: string; name: string }>;
    };
  }
}
