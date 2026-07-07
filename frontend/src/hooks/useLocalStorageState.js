import { useEffect, useState } from 'react'

export function useLocalStorageState(key, initialValue) {
  const [value, setValue] = useState(() => {
    try {
      const storedValue = localStorage.getItem(key)
      return storedValue ? JSON.parse(storedValue) : initialValue
    } catch {
      return initialValue
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // Local persistence is optional; the app should keep working without it.
    }
  }, [key, value])

  return [value, setValue]
}
