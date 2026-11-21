/** 前端统一错误对象：HTTP、网络与未知异常都归一到 `ApiError`。 */

import axios from 'axios'

import type { ApiErrorPayload } from '@/types/api'

export interface ApiErrorOptions {
  message: string
  code: string
  status?: number | null
  details?: unknown
  requestId?: string | null
  cause?: unknown
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number | null
  readonly details: unknown
  readonly requestId: string | null

  constructor({ message, code, status = null, details, requestId = null, cause }: ApiErrorOptions) {
    super(message, { cause })
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
    this.requestId = requestId
  }
}

/** 把任意异常转换为 `ApiError`；已是 `ApiError` 时原样返回。 */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error
  }

  if (axios.isAxiosError(error)) {
    const payload = error.response?.data as ApiErrorPayload | undefined
    return new ApiError({
      message: payload?.error?.message ?? error.message ?? '请求失败',
      code: payload?.error?.code ?? 'HTTP_ERROR',
      status: error.response?.status ?? null,
      details: payload?.error?.details,
      requestId: payload?.request_id ?? null,
      cause: error,
    })
  }

  if (error instanceof Error) {
    return new ApiError({ message: error.message, code: 'CLIENT_ERROR', cause: error })
  }

  return new ApiError({ message: '未知错误', code: 'UNKNOWN_ERROR', cause: error })
}

/** 取可展示的错误文案。 */
export function getErrorMessage(error: unknown): string {
  return toApiError(error).message
}
