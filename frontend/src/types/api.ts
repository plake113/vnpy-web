/** 后端统一契约类型（与 `backend/app/schemas/common.py` 对齐）。 */

/** 列表分页响应。 */
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

/** 统一错误响应体。 */
export interface ApiErrorPayload {
  error: {
    code: string
    message: string
    details?: unknown
  }
  request_id?: string
}
