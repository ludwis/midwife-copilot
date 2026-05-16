const BASE_URL = '/api'

function getHeaders(): Record<string, string> {
  const token = import.meta.env.VITE_ADMIN_TOKEN as string | undefined
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers['X-Admin-Token'] = token
  }
  return headers
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
  const token = import.meta.env.VITE_ADMIN_TOKEN as string | undefined
  const formData = new FormData()
  formData.append('file', file)
  formData.append('source_format', sourceFormat)

  const headers: Record<string, string> = {}
  if (token) {
    headers['X-Admin-Token'] = token
  }

  const res = await fetch(`${BASE_URL}/admin/kb/imports`, {
    method: 'POST',
    headers,
    body: formData,
  })
  return handleResponse<ImportCreatedResponse>(res)
}

export async function listImports(status?: string): Promise<{ imports: ImportSummary[] }> {
  const params = new URLSearchParams()
  if (status) params.set('status', status)

  const url = `${BASE_URL}/admin/kb/imports${params.size ? `?${params}` : ''}`
  const res = await fetch(url, { headers: getHeaders() })
  return handleResponse<{ imports: ImportSummary[] }>(res)
}

export async function getImport(id: string): Promise<ImportDetail> {
  const res = await fetch(`${BASE_URL}/admin/kb/imports/${encodeURIComponent(id)}`, {
    headers: getHeaders(),
  })
  return handleResponse<ImportDetail>(res)
}
