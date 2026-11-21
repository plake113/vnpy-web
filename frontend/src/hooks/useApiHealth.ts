/** 后端健康检查 hook 占位：外壳重建时接 /health 与 /health/ready，驱动连接状态展示。 */

import type { ApiStatus } from '@/stores/appStore'

export interface ApiHealthState {
  status: ApiStatus
  refresh: () => void
}

export function useApiHealth(): ApiHealthState {
  return { status: 'unknown', refresh: () => {} }
}
