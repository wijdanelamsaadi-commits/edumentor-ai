import { useEffect, useMemo, useState } from 'react'
import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  updateProfile,
} from 'firebase/auth'
import { getUserProfile } from '../services/api.js'
import { auth, googleProvider } from '../services/firebase.js'
import { AuthContext } from './authContext.js'

const DEFAULT_ROLE = 'student'
const AUTH_UID_STORAGE_KEY = 'edumentor:authUid'
const USER_CACHE_KEYS = [
  'edumentor:userProfile',
  'diagnosticResult',
  'edumentor:chapterProgress',
  'edumentor:quizResults',
  'edumentor:notifications',
  'edumentor:chatSessions',
]

export function AuthProvider({ children }) {
  const [currentUser, setCurrentUser] = useState(null)
  const [userProfile, setUserProfile] = useState(null)
  const [role, setRole] = useState(DEFAULT_ROLE)
  const [loading, setLoading] = useState(true)
  const [authReady, setAuthReady] = useState(false)

  useEffect(() => {
    let authSequence = 0

    const unsubscribe = onAuthStateChanged(auth, async (firebaseUser) => {
      const sequence = authSequence + 1
      authSequence = sequence
      setLoading(true)
      syncUserCacheOwner(firebaseUser)
      setCurrentUser(firebaseUser)
      setAuthReady(true)

      if (!firebaseUser) {
        setUserProfile(null)
        setRole(DEFAULT_ROLE)
        setLoading(false)
        return
      }

      const profile = await loadPostgresProfile()
      if (sequence !== authSequence) {
        return
      }

      setUserProfile(profile)
      setRole(normalizeRole(profile?.role))
      setLoading(false)
    })

    return unsubscribe
  }, [])

  async function login(email, password) {
    return signInWithEmailAndPassword(auth, email, password)
  }

  async function register(email, password, fullName = '') {
    const credential = await createUserWithEmailAndPassword(auth, email, password)

    if (fullName.trim()) {
      await updateProfile(credential.user, { displayName: fullName.trim() })
      await credential.user.getIdToken(true)
    }

    return credential
  }

  async function loginWithGoogle() {
    return signInWithPopup(auth, googleProvider)
  }

  async function logout() {
    await signOut(auth)
    clearUserCaches()
    localStorage.removeItem(AUTH_UID_STORAGE_KEY)
    setUserProfile(null)
    setRole(DEFAULT_ROLE)
  }

  function resetPassword(email) {
    return sendPasswordResetEmail(auth, email)
  }

  async function refreshAuthProfile() {
    const profile = await loadPostgresProfile()
    setUserProfile(profile)
    setRole(normalizeRole(profile?.role))
    return profile
  }

  const value = useMemo(() => ({
    currentUser,
    authReady,
    isAdmin: role === 'admin',
    isProfessor: role === 'professor',
    isStudent: role === 'student',
    isParent: role === 'parent',
    isUser: role === 'student',
    loading,
    login,
    loginWithGoogle,
    logout,
    register,
    resetPassword,
    role,
    userProfile,
    refreshAuthProfile,
  }), [authReady, currentUser, loading, role, userProfile])

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}

async function loadPostgresProfile() {
  try {
    return await getUserProfile()
  } catch {
    return null
  }
}

function normalizeRole(value) {
  const cleanRole = String(value || '').toLowerCase()
  if (cleanRole === 'admin' || cleanRole === 'professor' || cleanRole === 'student' || cleanRole === 'parent') {
    return cleanRole
  }
  if (cleanRole === 'user') {
    return 'student'
  }
  return DEFAULT_ROLE
}

function syncUserCacheOwner(firebaseUser) {
  const previousUid = localStorage.getItem(AUTH_UID_STORAGE_KEY)

  if (!firebaseUser) {
    clearUserCaches()
    localStorage.removeItem(AUTH_UID_STORAGE_KEY)
    return
  }

  if (previousUid && previousUid !== firebaseUser.uid) {
    clearUserCaches()
  }

  localStorage.setItem(AUTH_UID_STORAGE_KEY, firebaseUser.uid)
}

function clearUserCaches() {
  USER_CACHE_KEYS.forEach((key) => localStorage.removeItem(key))
}
