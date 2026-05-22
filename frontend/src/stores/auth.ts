import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  getAuth,
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithPopup,
  signOut as firebaseSignOut,
  type User,
} from 'firebase/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loading = ref(true)

  const isAuthenticated = computed(() => user.value !== null)

  const adminEmails = (import.meta.env.VITE_ADMIN_EMAIL as string)
    ?.split(',')
    .map((e: string) => e.trim())
    .filter(Boolean) ?? []

  const auth = getAuth()

  onAuthStateChanged(auth, (firebaseUser) => {
    if (firebaseUser && adminEmails.length > 0 && !adminEmails.includes(firebaseUser.email ?? '')) {
      firebaseSignOut(auth)
      user.value = null
    } else {
      user.value = firebaseUser
    }
    loading.value = false
  })

  async function signInWithGoogle() {
    const provider = new GoogleAuthProvider()
    await signInWithPopup(auth, provider)
  }

  async function signOut() {
    await firebaseSignOut(auth)
  }

  return { user, loading, isAuthenticated, signInWithGoogle, signOut }
})
