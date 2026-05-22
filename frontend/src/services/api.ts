import { getAuth } from 'firebase/auth'

const BASE_URL = '/api'

async function getAuthHeader(): Promise<Record<string, string>> {
  const currentUser = getAuth().currentUser
  if (!currentUser) return {}
  const token = await currentUser.getIdToken()
  return { Authorization: `Bearer ${token}` }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error((body as { error?: string }).error ?? res.statusText)
  }
  return res.json() as Promise<T>
}

// ---- Interfaces typed per kb-ingestion.yaml --------------------------------

export interface ImportCreatedResponse {
  import_id: string
  status: 'processing'
  submitted_at: string
}

export interface ImportSummary {
  import_id: string
  source_format: 'whatsapp_txt' | 'messenger_json'
  status: 'processing' | 'completed' | 'failed' | 'no_pairs_found'
  submitted_at: string
  completed_at: string | null
  chunks_extracted: number | null
  chunks_flagged_duplicate: number | null
}

export interface ImportDetail extends ImportSummary {
  error_message: string | null
}

// ---- API calls -------------------------------------------------------------

export async function createImport(
  file: File,
  sourceFormat: 'whatsapp_txt' | 'messenger_json',
): Promise<ImportCreatedResponse> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('source_format', sourceFormat)

  const res = await fetch(`${BASE_URL}/admin/kb/imports`, {
    method: 'POST',
    headers: await getAuthHeader(),
    body: formData,
  })
  return handleResponse<ImportCreatedResponse>(res)
}

export async function listImports(status?: string): Promise<{ imports: ImportSummary[] }> {
  const params = new URLSearchParams()
  if (status) params.set('status', status)

  const url = `${BASE_URL}/admin/kb/imports${params.size ? `?${params}` : ''}`
  const res = await fetch(url, { headers: await getAuthHeader() })
  return handleResponse<{ imports: ImportSummary[] }>(res)
}

export async function getImport(id: string): Promise<ImportDetail> {
  const res = await fetch(`${BASE_URL}/admin/kb/imports/${encodeURIComponent(id)}`, {
    headers: await getAuthHeader(),
  })
  return handleResponse<ImportDetail>(res)
}

// ---- Interfaces typed per kb-review.yaml ------------------------------------

export interface ChunkSummary {
  chunk_id: string
  question: string
  answer: string
  status: 'staged' | 'approved' | 'promoted' | 'discarded'
  source_type: 'export' | 'conversation_reply'
  import_id: string | null
  staged_at: string
  duplicate_flag: 'exact' | 'near' | null
  similarity_score: number | null
  duplicate_of: ChunkSummary | null
}

export interface ChunkDetail extends ChunkSummary {
  content_hash: string
  content_hash_before_edit: string | null
  reviewed_at: string | null
  reviewed_by: string | null
  production_vertex_id: string | null
  promoted_at: string | null
}

export interface ReviewAction {
  action: 'approve' | 'edit_approve' | 'discard'
  question?: string
  answer?: string
}

export interface ChunksListResponse {
  chunks: ChunkSummary[]
  next_cursor: string | null
  total_staged: number
}

export interface QueryResult {
  chunk_id: string
  question: string
  answer: string
  snippet: string
  promoted_at: string | null
}

export interface QueryResponse {
  query: string
  results: QueryResult[]
  total_results: number
}

// ---- Review & query API calls -----------------------------------------------

export async function listChunks(params: {
  status?: string
  importId?: string
  duplicateFlag?: string
  cursor?: string
  limit?: number
}): Promise<ChunksListResponse> {
  const q = new URLSearchParams()
  if (params.status) q.set('status', params.status)
  if (params.importId) q.set('import_id', params.importId)
  if (params.duplicateFlag) q.set('duplicate_flag', params.duplicateFlag)
  if (params.cursor) q.set('cursor', params.cursor)
  if (params.limit != null) q.set('limit', String(params.limit))

  const url = `${BASE_URL}/admin/kb/chunks${q.size ? `?${q}` : ''}`
  const res = await fetch(url, { headers: await getAuthHeader() })
  return handleResponse<ChunksListResponse>(res)
}

export async function getChunk(id: string): Promise<ChunkDetail> {
  const res = await fetch(`${BASE_URL}/admin/kb/chunks/${encodeURIComponent(id)}`, {
    headers: await getAuthHeader(),
  })
  return handleResponse<ChunkDetail>(res)
}

export async function reviewChunk(id: string, action: ReviewAction): Promise<ChunkDetail> {
  const res = await fetch(`${BASE_URL}/admin/kb/chunks/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...(await getAuthHeader()) },
    body: JSON.stringify(action),
  })
  return handleResponse<ChunkDetail>(res)
}

export async function queryProduction(q: string, limit?: number): Promise<QueryResponse> {
  const params = new URLSearchParams({ q })
  if (limit != null) params.set('limit', String(limit))

  const res = await fetch(`${BASE_URL}/admin/kb/production/query?${params}`, {
    headers: await getAuthHeader(),
  })
  return handleResponse<QueryResponse>(res)
}
