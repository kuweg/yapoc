export interface DriveStatus {
  connected: boolean
  user_email: string
  has_client_id: boolean
  has_client_secret: boolean
  has_refresh_token: boolean
}

export interface DriveFile {
  id: string
  name: string
  mime_type: string
  size?: string
  modified_time?: string
  web_view_link?: string
}

export interface DriveFileList {
  files: DriveFile[]
  next_page_token?: string
}

export async function getDriveStatus(): Promise<DriveStatus> {
  const res = await fetch(`/api/drive/oauth/status`)
  if (!res.ok) throw new Error(`getDriveStatus: ${res.status}`)
  return res.json()
}

export async function connectDrive(
  client_id: string,
  client_secret: string,
): Promise<{ auth_url: string; state: string }> {
  const res = await fetch(`/api/drive/oauth/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id, client_secret }),
  })
  if (!res.ok) throw new Error(`connectDrive: ${res.status}`)
  return res.json()
}

export async function disconnectDrive(): Promise<{ status: string; connected: boolean }> {
  const res = await fetch(`/api/drive/oauth/disconnect`, { method: 'POST' })
  if (!res.ok) throw new Error(`disconnectDrive: ${res.status}`)
  return res.json()
}

export async function listDriveFiles(query?: string, max_results?: number): Promise<DriveFileList> {
  const params = new URLSearchParams()
  if (query) params.set('query', query)
  if (max_results != null) params.set('max_results', String(max_results))
  const qs = params.toString()
  const res = await fetch(`/api/drive/files${qs ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error(`listDriveFiles: ${res.status}`)
  return res.json()
}

export interface DriveFileContent {
  file_id: string
  name: string
  mime_type: string
  summary: string
}

export async function getDriveFileContent(file_id: string): Promise<DriveFileContent> {
  const res = await fetch(`/api/drive/files/${encodeURIComponent(file_id)}/content`)
  if (!res.ok) throw new Error(`getDriveFileContent: ${res.status}`)
  return res.json()
}
