import type { ReelsApi } from './index'

declare global {
  interface Window {
    api: ReelsApi
  }
}

export {}
