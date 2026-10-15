/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue';

  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>;
  export default component;
}

interface ImportMetaEnv {
  /** BFF 基础地址；留空则走 Vite 代理（/api → BFF） */
  readonly VITE_BFF_BASE_URL?: string;
  /** 上传大小上限（MB）。与 BFF 的 `MAX_UPLOAD_MB` 同口径，默认 10。 */
  readonly VITE_MAX_UPLOAD_MB?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
