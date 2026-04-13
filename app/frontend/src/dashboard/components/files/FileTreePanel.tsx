import { useEffect } from 'react'
import { getFileTree } from '../../api/filesClient'
import { useDashboardStore } from '../../store/dashboardStore'
import { FileTreeNode } from './FileTreeNode'

export function FileTreePanel() {
  const { fileTree, setFileTree, openFilePath, openFileContent, openFileTruncated, closeFile } = useDashboardStore()

  useEffect(() => {
    if (fileTree.length === 0) {
      getFileTree(4).then(setFileTree).catch(console.error)
    }
  }, [])

  return (
    <div className="flex flex-col h-full bg-[#161B22] border-r border-[#30363D] w-[240px] flex-shrink-0">
      {/* Tree header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#30363D] bg-[#1C2128]">
        <span className="text-[#8B949E] text-xs font-medium">Files</span>
        <button
          onClick={() => getFileTree(4).then(setFileTree).catch(console.error)}
          className="text-[#484F58] hover:text-[#8B949E] text-xs transition-colors"
          title="Refresh tree"
        >
          ↻
        </button>
      </div>

      {/* Tree */}
      <div className="flex-1 overflow-y-auto py-1">
        {fileTree.length === 0 ? (
          <p className="text-[#484F58] text-xs px-3 py-2">Loading…</p>
        ) : (
          fileTree.map((node) => (
            <FileTreeNode key={node.path} node={node} depth={0} />
          ))
        )}
      </div>

      {/* File viewer */}
      {openFilePath && (
        <div className="border-t border-[#30363D] flex flex-col" style={{ maxHeight: '50%' }}>
          <div className="flex items-center justify-between px-3 py-1.5 bg-[#1C2128] border-b border-[#30363D]">
            <span className="text-[#FFB633] text-[10px] truncate flex-1" title={openFilePath}>
              {openFilePath}
            </span>
            <button
              onClick={closeFile}
              className="text-[#484F58] hover:text-[#E6EDF3] ml-2 flex-shrink-0 transition-colors"
            >
              ×
            </button>
          </div>
          {openFileTruncated && (
            <p className="text-[#D29922] text-[10px] px-3 py-1 bg-[#D2992215]">
              File truncated at 50,000 chars
            </p>
          )}
          <pre className="text-[#8B949E] text-[10px] p-3 overflow-auto flex-1 leading-relaxed whitespace-pre-wrap break-words">
            {openFileContent}
          </pre>
        </div>
      )}
    </div>
  )
}
