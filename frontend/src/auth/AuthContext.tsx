// Auth state for the whole app: tracks the signed-in Firebase user, exposes
// sign-in/out, and registers a token provider with the API layer so every
// request carries the user's current ID token.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  onAuthStateChanged,
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  sendEmailVerification,
  signOut as fbSignOut,
  type User,
} from 'firebase/auth'
import { auth, googleProvider, firebaseEnabled } from '../firebase'
import { setAuthTokenProvider } from '../api'

interface AuthState {
  user: User | null
  loading: boolean
  firebaseEnabled: boolean
  signInWithGoogle: () => Promise<void>
  // Email/password methods resolve to an informational notice string (e.g. "check
  // your inbox") when sign-in is blocked pending verification, or void on success.
  signInWithEmail: (email: string, password: string) => Promise<string | void>
  signUpWithEmail: (email: string, password: string) => Promise<string | void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  // When Firebase isn't configured we're in open mode: never "loading", no user.
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(firebaseEnabled)

  useEffect(() => {
    if (!firebaseEnabled || !auth) {
      setLoading(false)
      return
    }
    // Hand the API layer a fresh-token getter for the active user.
    setAuthTokenProvider(() => auth!.currentUser?.getIdToken() ?? Promise.resolve(null))
    const unsub = onAuthStateChanged(auth, (u) => {
      setUser(u)
      setLoading(false)
    })
    return unsub
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      firebaseEnabled,
      async signInWithGoogle() {
        if (!auth) return
        await signInWithPopup(auth, googleProvider)
      },
      async signInWithEmail(email, password) {
        if (!auth) return
        const cred = await signInWithEmailAndPassword(auth, email, password)
        // The backend rejects unverified emails (they're attacker-controllable),
        // so don't keep an unverified user signed in — re-send the link and stop.
        if (!cred.user.emailVerified) {
          await sendEmailVerification(cred.user)
          await fbSignOut(auth)
          return 'Email not verified — we re-sent the link. Verify it, then log in.'
        }
      },
      async signUpWithEmail(email, password) {
        if (!auth) return
        const cred = await createUserWithEmailAndPassword(auth, email, password)
        // New password accounts start unverified; send the link and sign back out
        // until the address is confirmed.
        await sendEmailVerification(cred.user)
        await fbSignOut(auth)
        return 'Account created. Check your email for a verification link, then log in.'
      },
      async signOut() {
        if (!auth) return
        await fbSignOut(auth)
      },
    }),
    [user, loading],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}
