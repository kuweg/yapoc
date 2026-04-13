import { useEffect, useState, useCallback } from 'react'
import type { VaultNode, VaultFile } from '../types'
import { getVaultTree, readVaultFile } from '../api/vaultClient'
import { VaultTree } from './VaultTree'
import { VaultFileViewer } from './VaultFileViewer'

export function VaultTab() {
  const [tree, setTree] = useState<VaultNode[]>([])
  const [treeLoading, setTreeLoading] = useState(true)
  const [treeError, setTreeError] = useState<string | null>(null)

  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [file, setFile] = useState<VaultFile | null>(null)
  const [fileLoading, setFileLoading] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)

  const loadTree = useCallback(() => {
    setTreeLoading(true)
    setTreeError(null)
    getVaultTree()
      .then(setTree)
      .catch((e: unknown) => setTreeError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setTreeLoading(false))
  }, [])

  useEffect(() => { loadTree() }, [loadTree])

  async function handleSelect(node: VaultNode) {
    if (node.is_dir) return
    setSelectedPath(node.path)
    setFileLoading(true)
    setFileError(null)
    setFile(null)
    try {
      const result = await readVaultFile(node.path)
      setFile(result)
    } catch (e: unknown) {
      setFileError(e instanceof Error ? e.message : 'failed to load')
    } finally {
      setFileLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-4 px-4 py-3 border-b border-zinc-800 flex-shrink-0">
        <h2 className="text-xs uppercase tracking-widest text-zinc-500">Vault</h2>
        <span className="text-zinc-500 text-xs">app/projects/</span>
        {treeError && <span className="text-red-400 text-xs">{treeError}</span>}
        <div className="flex-1" />
        <button
          onClick={loadTree}
          className="text-zinc-400 hover:text-zinc-300 text-sm transition-colors"
          title="Refresh tree"
        >
          ↻
        </button>
      </div>

      {/* Body: tree + viewer */}
      <div className="flex flex-1 overflow-hidden min-h-0">
        {/* Tree panel */}
        <div className="w-72 flex-shrink-0 border-r border-zinc-800 overflow-y-auto">
          {treeLoading ? (
            <div className="px-4 py-4 text-zinc-400 text-sm animate-pulse">loading…</div>
          ) : (
            <VaultTree
              nodes={tree}
              selectedPath={selectedPath}
              onSelect={handleSelect}
            />
          )}
        </div>

        {/* File viewer */}
        <VaultFileViewer
          file={file}
          loading={fileLoading}
          error={fileError}
        />
      </div>
    </div>
  )
}
