/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MOCK?: string
  readonly VITE_MOCK_MODE?: 'open' | 'single' | 'multi'
}
