import type { FileNode } from '../types'

export async function getFileTree(depth = 3): Promise<FileNode[]> {
  const res = await fetch(`/api/files/tree?depth=${depth}`)
  if (!res.ok) throw new Error(`file tree ${res.status}`)
  return res.json()
}

export async function readFile(path: string): Promise<{ path: string; content: string; truncated: boolean; size: number }> {
  const res = await fetch(`/api/files/read?path=${encodeURIComponent(path)}`)
  if (!res.ok) throw new Error(`read file ${res.status}`)
  return res.json()
}
