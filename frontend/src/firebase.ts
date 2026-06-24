// Firebase app + auth initialisation, driven entirely by VITE_FIREBASE_* env
// vars (see .env.example). When the config is absent we leave Firebase
// uninitialised and `firebaseEnabled` is false — the app then runs in open mode,
// mirroring the backend, which only enforces auth when it has credentials.
import { initializeApp, type FirebaseApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider, type Auth } from 'firebase/auth'

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
}

export const firebaseEnabled = Boolean(config.apiKey && config.authDomain && config.projectId)

let app: FirebaseApp | undefined
let auth: Auth | undefined

if (firebaseEnabled) {
  app = initializeApp(config)
  auth = getAuth(app)
}

export { auth }
export const googleProvider = new GoogleAuthProvider()
