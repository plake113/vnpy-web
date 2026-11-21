/** 全局偏好（zustand）：主题、涨跌配色、侧栏折叠。 */

import { create } from 'zustand'

export type ThemeMode = 'light' | 'dark' | 'system'
export type PriceScheme = 'cn' | 'intl'

interface PreferencesState {
  theme: ThemeMode
  priceScheme: PriceScheme
  railCollapsed: boolean
  setTheme: (theme: ThemeMode) => void
  setPriceScheme: (scheme: PriceScheme) => void
  setRailCollapsed: (collapsed: boolean) => void
}

/** 占位实现：localStorage 持久化与 `html[data-theme]` 写入待外壳重建时补。 */
export const usePreferencesStore = create<PreferencesState>((set) => ({
  theme: 'light',
  priceScheme: 'cn',
  railCollapsed: false,
  setTheme: (theme) => set({ theme }),
  setPriceScheme: (priceScheme) => set({ priceScheme }),
  setRailCollapsed: (railCollapsed) => set({ railCollapsed }),
}))
