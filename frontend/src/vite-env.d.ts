/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API 基地址；默认 /api/v1，由 Vite 代理或 Nginx 转发 */
  readonly VITE_API_BASE_URL?: string
  /** 开发代理目标，仅 vite.config.ts 使用 */
  readonly VITE_PROXY_TARGET?: string
  /** 概览页「打开 API 文档」按钮地址 */
  readonly VITE_API_DOCS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
