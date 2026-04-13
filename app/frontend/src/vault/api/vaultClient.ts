import type { VaultNode, VaultFile } from '../types'

export async function getVaultTree(depth = 5): Promise<VaultNode[]> {
  const res = await fetch(`/api/vault/tree?depth=${depth}`)
  if (!res.ok) throw new Error(`vault tree: ${res.status}`)
  return res.json() as Promise<VaultNode[]>
}

export async function readVaultFile(path: string): Promise<VaultFile> {
  const res = await fetch(`/api/vault/read?path=${encodeURIComponent(path)}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body?.detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<VaultFile>
}
