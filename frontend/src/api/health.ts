/** 健康检查接口：与 `backend/app/schemas/health.py` 对齐。 */

import { http } from './client'

/** 存活探针响应（`GET /api/v1/health`）。 */
export interface HealthResponse {
  status: 'ok'
  app: string
  version: string
  env: string
  timestamp: string
}

/** 就绪探针响应（`GET /api/v1/health/ready`）。 */
export interface ReadinessResponse {
  status: 'ready' | 'degraded'
  database: 'ok' | 'unavailable'
  timestamp: string
}

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await http.get<HealthResponse>('/health')
  return data
}

export async function fetchReadiness(): Promise<ReadinessResponse> {
  const { data } = await http.get<ReadinessResponse>('/health/ready')
  return data
}
