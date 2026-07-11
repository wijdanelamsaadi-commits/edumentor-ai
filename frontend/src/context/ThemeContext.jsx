import { useEffect, useMemo, useState } from 'react'
import { ThemeContext } from './themeContext.js'

export const THEME_STORAGE_KEY = 'edumentor:theme'

function getStoredTheme() {
  const storedTheme = localStorage.getItem(THEME_STORAGE_KEY)
  return ['light', 'dark', 'system'].includes(storedTheme) ? storedTheme : 'light'
}

function getSystemTheme() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => getStoredTheme())
  const [systemTheme, setSystemTheme] = useState(() => getSystemTheme())

  useEffect(() => {
    const mediaQuery = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mediaQuery) return undefined

    function handleSystemThemeChange(event) {
      setSystemTheme(event.matches ? 'dark' : 'light')
    }

    mediaQuery.addEventListener('change', handleSystemThemeChange)
    return () => mediaQuery.removeEventListener('change', handleSystemThemeChange)
  }, [])

  useEffect(() => {
    const resolvedTheme = theme === 'system' ? systemTheme : theme
    document.documentElement.dataset.theme = resolvedTheme
    document.documentElement.dataset.themePreference = theme
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  }, [systemTheme, theme])

  const value = useMemo(() => ({
    resolvedTheme: theme === 'system' ? systemTheme : theme,
    setTheme,
    systemTheme,
    theme,
  }), [systemTheme, theme])

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  )
}
