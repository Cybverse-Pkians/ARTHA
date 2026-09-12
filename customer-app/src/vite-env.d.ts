/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ARTHA_API?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
