/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Absolute API base URL. Left unset in normal deployments: the Vite dev
   * server and the production nginx both proxy the API paths, so the browser
   * sees a single origin.
   */
  readonly VITE_API_BASE_URL?: string
  /** Poll interval in milliseconds. Defaults to 4000. */
  readonly VITE_POLL_INTERVAL_MS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
