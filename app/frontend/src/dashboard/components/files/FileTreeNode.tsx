import { useState } from 'react'
import type { FileNode } from '../../types'
import { readFile } from '../../api/filesClient'
import { useDashboardStore } from '../../store/dashboardStore'

interface Props {
  node: FileNode
  depth?: number
}

const CHEVRON_RIGHT = '▶'
const CHEVRON_DOWN  = '▼'
const ICON_FILE = '·'
const ICON_DIR_OPEN = '📂'
const ICON_DIR_CLOSED = '📁'

// Extension → colour
function fileColor(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  if (['py'].includes(ext)) return '#3572A5'
  if (['ts', 'tsx'].includes(ext)) return '#3178C6'
  if (['js', 'jsx'].includes(ext)) return '#F1E05A'
  if (['md', 'txt'].includes(ext)) return '#8B949E'
  if (['json', 'yaml', 'yml', 'toml'].includes(ext)) return '#D29922'
  if (['css', 'scss'].includes(ext)) return '#CC6699'
  if (['html'].includes(ext)) return '#E34C26'
  if (['sh', 'bash'].includes(ext)) return '#3FB950'
  return '#8B949E'
}

export function FileTreeNode({ node, depth = 0 }: Props) {
  const [expanded, setExpanded] = useState(depth === 0 && node.is_dir)
  const { openFile } = useDashboardStore()

  async function handleClick() {
    if (node.is_dir) {
      setExpanded((v) => !v)
    } else {
      try {
        const result = await readFile(node.path)
        openFile(result.path, result.content, result.truncated)
      } catch (err) {
        console.error('read file error', err)
      }
    }
  }

  const indent = depth * 12

  return (
    <div>
      <button
        onClick={handleClick}
        className="flex items-center gap-1 w-full text-left px-2 py-0.5 hover:bg-[#21262D] rounded text-[11px] transition-colors"
        style={{ paddingLeft: `${8 + indent}px` }}
      >
        {node.is_dir ? (
          <>
            <span className="text-[#484F58] text-[9px] w-3">
              {expanded ? CHEVRON_DOWN : CHEVRON_RIGHT}
            </span>
            <span>{expanded ? ICON_DIR_OPEN : ICON_DIR_CLOSED}</span>
            <span className="text-[#E6EDF3] truncate">{node.name}</span>
          </>
        ) : (
          <>
            <span className="w-3" />
            <span className="text-[#484F58] text-[9px]">{ICON_FILE}</span>
            <span style={{ color: fileColor(node.name) }} className="truncate">{node.name}</span>
          </>
        )}
      </button>

      {node.is_dir && expanded && node.children && (
        <div>
          {node.children.map((child) => (
            <FileTreeNode key={child.path} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}
