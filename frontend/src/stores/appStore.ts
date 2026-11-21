/** 全局 UI 状态（zustand）：toast 与后端连接状态。 */

import { create } from 'zustand'

export type ApiStatus = 'unknown' | 'online' | 'offline'
export type ToastTone = 'info' | 'success' | 'error'

export interface Toast {
  id: string
  message: string
  tone: ToastTone
}

interface AppState {
  apiStatus: ApiStatus
  toasts: Toast[]
  setApiStatus: (status: ApiStatus) => void
  pushToast: (message: string, tone?: ToastTone) => void
  dismissToast: (id: string) => void
}

/** 占位实现：自动消失与队列渲染待外壳重建时补（Toast 视图）。 */
let toastSeq = 0

export const useAppStore = create<AppState>((set) => ({
  apiStatus: 'unknown',
  toasts: [],
  setApiStatus: (apiStatus) => set({ apiStatus }),
  pushToast: (message, tone = 'info') =>
    set((state) => ({
      toasts: [...state.toasts, { id: `toast-${++toastSeq}`, message, tone }],
    })),
  dismissToast: (id) =>
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
}))
