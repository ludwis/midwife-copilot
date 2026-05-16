import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listChunks,
  listImports,
  reviewChunk,
  queryProduction as apiQueryProduction,
  type ChunkSummary,
  type ImportSummary,
  type QueryResult,
} from '@/services/api'

export const useKbStore = defineStore('kb', () => {
  const stagedChunks = ref<ChunkSummary[]>([])
  const nextCursor = ref<string | null>(null)
  const imports = ref<ImportSummary[]>([])

  async function fetchStagedChunks(append = false) {
    const cursor = append ? (nextCursor.value ?? undefined) : undefined
    const data = await listChunks({ status: 'staged', cursor })
    if (append) {
      stagedChunks.value.push(...data.chunks)
    } else {
      stagedChunks.value = data.chunks
    }
    nextCursor.value = data.next_cursor
  }

  async function approveChunk(id: string) {
    await reviewChunk(id, { action: 'approve' })
    stagedChunks.value = stagedChunks.value.filter((c) => c.chunk_id !== id)
  }

  async function editApproveChunk(id: string, question: string, answer: string) {
    await reviewChunk(id, { action: 'edit_approve', question, answer })
    stagedChunks.value = stagedChunks.value.filter((c) => c.chunk_id !== id)
  }

  async function discardChunk(id: string) {
    await reviewChunk(id, { action: 'discard' })
    stagedChunks.value = stagedChunks.value.filter((c) => c.chunk_id !== id)
  }

  async function queryProduction(q: string): Promise<QueryResult[]> {
    const data = await apiQueryProduction(q)
    return data.results
  }

  async function fetchImports() {
    const data = await listImports()
    imports.value = data.imports
  }

  return {
    stagedChunks,
    nextCursor,
    imports,
    fetchStagedChunks,
    approveChunk,
    editApproveChunk,
    discardChunk,
    queryProduction,
    fetchImports,
  }
})
