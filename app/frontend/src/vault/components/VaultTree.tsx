import { useState } from 'react'
import type { VaultNode } from '../types'

interface Props {
  nodes: VaultNode[]
  selectedPath: string | null
  onSelect: (node: VaultNode) => void
  depth?: number
}

// Extension → color
function fileColor(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  if (ext === 'py')                       return '#FFB633'
  if (['ts', 'tsx'].includes(ext))        return '#3178C6'
  if (['js', 'jsx'].includes(ext))        return '#F1E05A'
  if (['md', 'mdx'].includes(ext))        return '#a0a090'
  if (['json', 'yaml', 'yml', 'toml'].includes(ext)) return '#D29922'
  if (['css', 'scss'].includes(ext))      return '#CC6699'
  if (['html', 'htm', 'xml'].includes(ext)) return '#E34C26'
  if (['sh', 'bash', 'zsh'].includes(ext)) return '#33ff66'
  if (['rs'].includes(ext))               return '#F74C00'
  if (['go'].includes(ext))               return '#00ADD8'
  if (['sql'].includes(ext))              return '#e88c2a'
  if (['svg', 'png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) return '#cc88ff'
  if (ext === 'pdf')                      return '#ff3333'
  return '#a0a090'
}

function fileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico', 'bmp'].includes(ext)) return '◈'
  if (ext === 'pdf')                return '◉'
  if (ext === 'md' || ext === 'mdx') return '◎'
  if (['zip', 'tar', 'gz', 'bz2'].includes(ext)) return '◫'
  return '◦'
}

function formatSize(bytes?: number): string {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}K`
  return `${(bytes / 1024 / 1024).toFixed(1)}M`
}

function VaultTreeNode({
  node, selectedPath, onSelect, depth,
}: {
  node: VaultNode
  selectedPath: string | null
  onSelect: (n: VaultNode) => void
  depth: number
}) {
  const [expanded, setExpanded] = useState(depth === 0)
  const isSelected = selectedPath === node.path
  const indent = depth * 16

  if (node.is_dir) {
    return (
      <div>
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-2 w-full text-left px-2 py-1 hover:bg-zinc-800 text-sm transition-colors"
          style={{ paddingLeft: `${8 + indent}px` }}
        >
          <span className="text-zinc-500 text-xs w-3 flex-shrink-0">
            {expanded ? '▼' : '▶'}
          </span>
          <span className="text-zinc-400 truncate">{node.name}/</span>
        </button>
        {expanded && node.children && (
          <div>
            {node.children.map((child) => (
              <VaultTreeNode
                key={child.path}
                node={child}
                selectedPath={selectedPath}
                onSelect={onSelect}
                depth={depth + 1}
              />
            ))}
            {node.children.length === 0 && (
              <div className="text-zinc-500 text-xs italic" style={{ paddingLeft: `${8 + (depth + 1) * 16}px` }}>
                empty
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <button
      onClick={() => onSelect(node)}
      className={[
        'flex items-center gap-2 w-full text-left px-2 py-1 text-sm transition-colors',
        isSelected ? 'bg-zinc-700' : 'hover:bg-zinc-800',
      ].join(' ')}
      style={{ paddingLeft: `${8 + indent + 14}px` }}
    >
      <span style={{ color: fileColor(node.name) }} className="flex-shrink-0 text-xs">
        {fileIcon(node.name)}
      </span>
      <span style={{ color: fileColor(node.name) }} className="truncate flex-1">
        {node.name}
      </span>
      {node.size != null && (
        <span className="text-zinc-500 text-xs flex-shrink-0 tabular-nums">
          {formatSize(node.size)}
        </span>
      )}
    </button>
  )
}

export function VaultTree({ nodes, selectedPath, onSelect, depth = 0 }: Props) {
  if (nodes.length === 0) {
    return (
      <div className="px-4 py-5 text-zinc-500 text-sm italic">
        No files yet.<br />
        <span className="text-zinc-500">projects/ is empty.</span>
      </div>
    )
  }
  return (
    <div>
      {nodes.map((node) => (
        <VaultTreeNode
          key={node.path}
          node={node}
          selectedPath={selectedPath}
          onSelect={onSelect}
          depth={depth}
        />
      ))}
    </div>
  )
}
