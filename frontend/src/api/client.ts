/** 全局 axios 实例：基地址来自 `VITE_API_BASE_URL`，错误统一转换为 `ApiError`。 */

import axios from 'axios'

import { toApiError } from '@/utils/errors'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15_000,
})

http.interceptors.response.use(
  (response) => response,
  (error: unknown) => Promise.reject(toApiError(error)),
)
