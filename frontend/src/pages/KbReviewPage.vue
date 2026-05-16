<template>
  <div class="min-h-screen bg-gray-50 p-8">
    <div class="max-w-xl mx-auto">
      <h1 class="text-2xl font-semibold text-gray-800 mb-6">Knowledge Base</h1>

      <!-- Upload card -->
      <div class="bg-white rounded-2xl shadow-md p-8">
        <h2 class="text-lg font-medium text-gray-700 mb-4">Upload Chat Export</h2>

        <!-- File input -->
        <label class="block mb-4">
          <span class="text-sm text-gray-600 mb-1 block">File (.txt or .json)</span>
          <input
            type="file"
            accept=".txt,.json"
            @change="onFileChange"
            :disabled="uploading || polling"
            class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100 disabled:opacity-60"
          />
        </label>

        <!-- Source format radio -->
        <fieldset class="mb-6">
          <legend class="text-sm text-gray-600 mb-2">Source format</legend>
          <div class="flex gap-6">
            <label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input
                type="radio"
                value="whatsapp_txt"
                v-model="sourceFormat"
                :disabled="uploading || polling"
                class="accent-indigo-600"
              />
              WhatsApp (.txt)
            </label>
            <label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input
                type="radio"
                value="messenger_json"
                v-model="sourceFormat"
                :disabled="uploading || polling"
                class="accent-indigo-600"
              />
              Messenger (.json)
            </label>
          </div>
        </fieldset>

        <!-- Upload button -->
        <button
          @click="handleUpload"
          :disabled="!selectedFile || uploading || polling"
          class="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          <span
            v-if="uploading"
            class="inline-block w-4 h-4 border-2 border-indigo-300 border-t-white rounded-full animate-spin"
          />
          {{ uploading ? 'Uploading…' : 'Upload & Extract' }}
        </button>

        <!-- Error -->
        <p v-if="errorMessage" class="mt-4 text-sm text-red-600">{{ errorMessage }}</p>

        <!-- Status section -->
        <div v-if="importId" class="mt-6 border-t pt-5">
          <div class="flex items-center gap-3 mb-3">
            <span class="text-sm text-gray-600">Status:</span>
            <span :class="statusBadgeClass" class="px-2.5 py-0.5 rounded-full text-xs font-semibold">
              {{ statusLabel }}
            </span>
            <span
              v-if="polling"
              class="inline-block w-3.5 h-3.5 border-2 border-gray-300 border-t-indigo-500 rounded-full animate-spin"
            />
          </div>

          <!-- Completed summary -->
          <div v-if="importDetail && importDetail.status === 'completed'" class="text-sm text-gray-700 space-y-1">
            <p>Chunks extracted: <span class="font-medium">{{ importDetail.chunks_extracted ?? 0 }}</span></p>
            <p>Duplicates flagged: <span class="font-medium">{{ importDetail.chunks_flagged_duplicate ?? 0 }}</span></p>
          </div>

          <!-- Failed error -->
          <p v-if="importDetail?.status === 'failed' && importDetail.error_message" class="text-sm text-red-600">
            {{ importDetail.error_message }}
          </p>

          <!-- No pairs -->
          <p v-if="importDetail?.status === 'no_pairs_found'" class="text-sm text-gray-500">
            No Q&A pairs could be extracted from this export.
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { createImport, getImport } from '../services/api'
import type { ImportDetail } from '../services/api'

const selectedFile = ref<File | null>(null)
const sourceFormat = ref<'whatsapp_txt' | 'messenger_json'>('whatsapp_txt')
const uploading = ref(false)
const polling = ref(false)
const errorMessage = ref('')
const importId = ref<string | null>(null)
const importDetail = ref<ImportDetail | null>(null)

let pollInterval: ReturnType<typeof setInterval> | null = null

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'no_pairs_found'])

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  selectedFile.value = input.files?.[0] ?? null
}

async function handleUpload() {
  if (!selectedFile.value) return
  errorMessage.value = ''
  importId.value = null
  importDetail.value = null
  uploading.value = true

  try {
    const created = await createImport(selectedFile.value, sourceFormat.value)
    importId.value = created.import_id
    startPolling(created.import_id)
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : 'Upload failed. Please try again.'
  } finally {
    uploading.value = false
  }
}

function startPolling(id: string) {
  polling.value = true
  pollInterval = setInterval(async () => {
    try {
      const detail = await getImport(id)
      importDetail.value = detail
      if (TERMINAL_STATUSES.has(detail.status)) {
        stopPolling()
      }
    } catch {
      // keep polling on transient errors
    }
  }, 3000)
}

function stopPolling() {
  polling.value = false
  if (pollInterval !== null) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

onUnmounted(stopPolling)

const statusLabel = computed(() => {
  const s = importDetail.value?.status
  if (!s) return 'processing'
  const labels: Record<string, string> = {
    processing: 'Processing',
    completed: 'Completed',
    failed: 'Failed',
    no_pairs_found: 'No pairs found',
  }
  return labels[s] ?? s
})

const statusBadgeClass = computed(() => {
  const s = importDetail.value?.status
  if (s === 'completed') return 'bg-green-100 text-green-800'
  if (s === 'failed') return 'bg-red-100 text-red-800'
  if (s === 'no_pairs_found') return 'bg-yellow-100 text-yellow-800'
  return 'bg-blue-100 text-blue-800'
})
</script>
