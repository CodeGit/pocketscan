export type Status = 'pending' | 'running' | 'succeeded' | 'failed'

export interface JobProtein {
  accession: string
  status: Status
  error: string | null
}

export interface Job {
  id: number
  request_key: string
  analysis: string
  created_at: string // ISO 8601; JSON has no date type
  status: Status
  proteins: JobProtein[]
}

export interface Pocket {
  accession: string
  rank: number
  score: number
  volume_a3: number
  mean_sasa_a2: number | null // null when no residue matched
  mean_plddt: number | null
  residues: string[] // "A:207:MET"
}

export interface PocketPage {
  total: number // every match, before limit and offset
  items: Pocket[]
}

export type PocketSort = 'rank' | 'score' | 'volume_a3' | 'mean_sasa_a2' | 'mean_plddt'

export interface PocketQuery {
  accession?: string
  min_score?: number
  min_volume_a3?: number
  min_mean_plddt?: number
  sort?: PocketSort
  order?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    // 404s carry {"detail": "job not found"}; 422s carry a list of problems.
    const detail = body?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg).join('; ')
          : response.statusText
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export function createJob(accessions: string[]): Promise<Job> {
  return request<Job>('/jobs', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ accessions }),
  })
}

export function getJob(id: number): Promise<Job> {
  return request<Job>(`/jobs/${id}`)
}

export function getPockets(id: number, query: PocketQuery = {}): Promise<PocketPage> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  return request<PocketPage>(`/jobs/${id}/pockets?${params}`)
}
