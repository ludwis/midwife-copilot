<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50">
    <div class="bg-white rounded-2xl shadow-md p-10 w-full max-w-sm text-center">
      <h1 class="text-2xl font-semibold text-gray-800 mb-2">Stilla Admin</h1>
      <p class="text-sm text-gray-500 mb-8">Sign in to manage your knowledge base</p>

      <p v-if="errorMessage" class="text-sm text-red-600 mb-4">{{ errorMessage }}</p>

      <button
        @click="handleSignIn"
        :disabled="signingIn"
        class="w-full flex items-center justify-center gap-3 px-4 py-2.5 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
      >
        <span v-if="signingIn" class="inline-block w-4 h-4 border-2 border-gray-300 border-t-indigo-500 rounded-full animate-spin" />
        <svg v-else viewBox="0 0 48 48" class="w-5 h-5" aria-hidden="true">
          <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
          <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
          <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
          <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
          <path fill="none" d="M0 0h48v48H0z"/>
        </svg>
        {{ signingIn ? 'Signing in…' : 'Sign in with Google' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const signingIn = ref(false)
const errorMessage = ref('')

watchEffect(() => {
  if (authStore.isAuthenticated) {
    router.push('/kb')
  }
})

async function handleSignIn() {
  signingIn.value = true
  errorMessage.value = ''
  try {
    await authStore.signInWithGoogle()
    router.push('/kb')
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : 'Sign-in failed. Please try again.'
  } finally {
    signingIn.value = false
  }
}
</script>
