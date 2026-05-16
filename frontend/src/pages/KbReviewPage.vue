<template>
  <div class="min-h-screen bg-gray-50 p-8">
    <div class="max-w-4xl mx-auto">
      <h1 class="text-2xl font-semibold text-gray-800 mb-6">Knowledge Base</h1>

      <!-- Upload card -->
      <div class="bg-white rounded-2xl shadow-md p-8 max-w-xl">
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

      <!-- Review Queue -->
      <div class="mt-10">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-medium text-gray-700">
            Review Queue
            <span class="ml-2 px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-700">
              {{ kbStore.stagedChunks.length }}
            </span>
          </h2>
          <button
            @click="kbStore.fetchStagedChunks()"
            :disabled="loadingChunks"
            class="text-sm text-indigo-600 hover:text-indigo-800 disabled:opacity-50"
          >
            Refresh
          </button>
        </div>

        <div v-if="loadingChunks" class="text-sm text-gray-500 py-4">Loading…</div>

        <p v-else-if="kbStore.stagedChunks.length === 0" class="text-sm text-gray-500 py-4">
          No staged chunks pending review.
        </p>

        <div v-else class="space-y-4">
          <div
            v-for="chunk in kbStore.stagedChunks"
            :key="chunk.chunk_id"
            class="bg-white rounded-2xl shadow-md p-6"
          >
            <!-- Header row: badges + timestamp -->
            <div class="flex items-center gap-2 mb-3 flex-wrap">
              <!-- Source badge -->
              <span class="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600">
                {{ chunk.source_type === 'export' ? 'Export' : 'Conversation' }}
              </span>

              <!-- Duplicate warning badge -->
              <span
                v-if="chunk.duplicate_flag"
                class="px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800 flex items-center gap-1"
              >
                ⚠ {{ chunk.duplicate_flag === 'exact' ? 'Exact duplicate' : 'Near duplicate' }}
                <span v-if="chunk.similarity_score != null">({{ (chunk.similarity_score * 100).toFixed(0) }}%)</span>
                <span v-if="chunk.duplicate_of"> — similar to {{ chunk.duplicate_of.chunk_id.slice(0, 8) }}</span>
              </span>

              <span class="ml-auto text-xs text-gray-400">
                {{ formatDate(chunk.staged_at) }}
              </span>
            </div>

            <!-- Edit mode -->
            <template v-if="editingId === chunk.chunk_id">
              <div class="space-y-3 mb-4">
                <div>
                  <label class="block text-xs font-medium text-gray-600 mb-1">Question</label>
                  <textarea
                    v-model="editQuestion"
                    rows="2"
                    class="w-full text-sm border border-gray-300 rounded-lg p-2 focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                </div>
                <div>
                  <label class="block text-xs font-medium text-gray-600 mb-1">Answer</label>
                  <textarea
                    v-model="editAnswer"
                    rows="4"
                    class="w-full text-sm border border-gray-300 rounded-lg p-2 focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                </div>
              </div>
              <div class="flex gap-2 flex-wrap">
                <button
                  @click="submitEditApprove(chunk.chunk_id)"
                  :disabled="!!actionLoading[chunk.chunk_id]"
                  class="py-1.5 px-3 rounded-lg text-xs font-medium text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 transition-colors"
                >
                  {{ actionLoading[chunk.chunk_id] ? 'Saving…' : 'Save & Approve' }}
                </button>
                <button
                  @click="cancelEdit"
                  :disabled="!!actionLoading[chunk.chunk_id]"
                  class="py-1.5 px-3 rounded-lg text-xs font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </template>

            <!-- Read mode -->
            <template v-else>
              <div class="mb-3">
                <p class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Question</p>
                <p class="text-sm text-gray-800">{{ chunk.question }}</p>
              </div>
              <div class="mb-4">
                <p class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Answer</p>
                <p class="text-sm text-gray-700 whitespace-pre-wrap">{{ chunk.answer }}</p>
              </div>

              <!-- Action buttons -->
              <div class="flex gap-2 flex-wrap">
                <button
                  @click="handleApprove(chunk.chunk_id)"
                  :disabled="!!actionLoading[chunk.chunk_id]"
                  class="py-1.5 px-3 rounded-lg text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                >
                  {{ actionLoading[chunk.chunk_id] === 'approve' ? 'Approving…' : 'Approve' }}
                </button>
                <button
                  @click="startEdit(chunk)"
                  :disabled="!!actionLoading[chunk.chunk_id]"
                  class="py-1.5 px-3 rounded-lg text-xs font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 disabled:opacity-50 transition-colors"
                >
                  Edit &amp; Approve
                </button>
                <button
                  @click="handleDiscard(chunk.chunk_id)"
                  :disabled="!!actionLoading[chunk.chunk_id]"
                  class="py-1.5 px-3 rounded-lg text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 disabled:opacity-50 transition-colors"
                >
                  {{ actionLoading[chunk.chunk_id] === 'discard' ? 'Discarding…' : 'Discard' }}
                </button>
              </div>
            </template>

            <!-- Per-chunk error -->
            <p v-if="actionError[chunk.chunk_id]" class="mt-2 text-xs text-red-600">
              {{ actionError[chunk.chunk_id] }}
            </p>
          </div>
        </div>

        <!-- Load more -->
        <div v-if="kbStore.nextCursor" class="mt-4 text-center">
          <button
            @click="loadMore"
            :disabled="loadingMore"
            class="py-2 px-6 rounded-lg text-sm font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 disabled:opacity-50 transition-colors"
          >
            {{ loadingMore ? 'Loading…' : 'Load more' }}
          </button>
        </div>
      </div>

      <!-- Production Query Panel -->
      <div class="mt-10 bg-white rounded-2xl shadow-md p-8">
        <h2 class="text-lg font-medium text-gray-700 mb-4">Query Production Index</h2>

        <div class="flex gap-3 mb-4">
          <input
            v-model="queryText"
            type="text"
            placeholder="Enter a midwifery question…"
            @keydown.enter="runQuery"
            class="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
          <button
            @click="runQuery"
            :disabled="!queryText.trim() || queryLoading"
            class="py-2 px-4 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          >
            {{ queryLoading ? 'Searching…' : 'Search' }}
          </button>
        </div>

        <p v-if="queryError" class="text-sm text-red-600 mb-3">{{ queryError }}</p>

        <div v-if="queryResults.length > 0" class="space-y-3">
          <div
            v-for="result in queryResults"
            :key="result.chunk_id"
            class="border border-gray-100 rounded-xl p-4"
          >
            <p class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Question</p>
            <p class="text-sm text-gray-800 mb-2">{{ result.question }}</p>
            <p class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Snippet</p>
            <p class="text-sm text-gray-600 italic">{{ result.snippet }}</p>
          </div>
        </div>

        <p v-else-if="queryRan && queryResults.length === 0" class="text-sm text-gray-500">
          No results found.
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import { createImport, getImport } from '../services/api'
import type { ImportDetail, ChunkSummary, QueryResult } from '../services/api'
import { useKbStore } from '../stores/kb'

// ---- Upload logic (unchanged) -----------------------------------------------

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
        // Refresh review queue when import completes
        if (detail.status === 'completed') {
          kbStore.fetchStagedChunks()
        }
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

// ---- Review queue -----------------------------------------------------------

const kbStore = useKbStore()
const loadingChunks = ref(false)
const loadingMore = ref(false)
const actionLoading = reactive<Record<string, string | false>>({})
const actionError = reactive<Record<string, string>>({})

const editingId = ref<string | null>(null)
const editQuestion = ref('')
const editAnswer = ref('')

onMounted(async () => {
  loadingChunks.value = true
  try {
    await kbStore.fetchStagedChunks()
  } finally {
    loadingChunks.value = false
  }
})

async function loadMore() {
  loadingMore.value = true
  try {
    await kbStore.fetchStagedChunks(true)
  } finally {
    loadingMore.value = false
  }
}

async function handleApprove(id: string) {
  actionLoading[id] = 'approve'
  delete actionError[id]
  try {
    await kbStore.approveChunk(id)
  } catch (err: unknown) {
    actionError[id] = err instanceof Error ? err.message : 'Action failed.'
  } finally {
    actionLoading[id] = false
  }
}

async function handleDiscard(id: string) {
  actionLoading[id] = 'discard'
  delete actionError[id]
  try {
    await kbStore.discardChunk(id)
  } catch (err: unknown) {
    actionError[id] = err instanceof Error ? err.message : 'Action failed.'
  } finally {
    actionLoading[id] = false
  }
}

function startEdit(chunk: ChunkSummary) {
  editingId.value = chunk.chunk_id
  editQuestion.value = chunk.question
  editAnswer.value = chunk.answer
}

function cancelEdit() {
  editingId.value = null
  editQuestion.value = ''
  editAnswer.value = ''
}

async function submitEditApprove(id: string) {
  actionLoading[id] = 'edit_approve'
  delete actionError[id]
  try {
    await kbStore.editApproveChunk(id, editQuestion.value, editAnswer.value)
    cancelEdit()
  } catch (err: unknown) {
    actionError[id] = err instanceof Error ? err.message : 'Action failed.'
  } finally {
    actionLoading[id] = false
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

// ---- Production query -------------------------------------------------------

const queryText = ref('')
const queryResults = ref<QueryResult[]>([])
const queryLoading = ref(false)
const queryError = ref('')
const queryRan = ref(false)

async function runQuery() {
  const q = queryText.value.trim()
  if (!q) return
  queryError.value = ''
  queryLoading.value = true
  queryRan.value = false
  try {
    queryResults.value = await kbStore.queryProduction(q)
    queryRan.value = true
  } catch (err: unknown) {
    queryError.value = err instanceof Error ? err.message : 'Query failed.'
  } finally {
    queryLoading.value = false
  }
}
</script>
