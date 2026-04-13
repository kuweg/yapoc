import { useState, useEffect } from 'react'

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 5) return 'just now'
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export function formatAbsoluteTime(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export function useRelativeTime(iso: string | null | undefined): string {
  const [label, setLabel] = useState(() => formatRelativeTime(iso))
  useEffect(() => {
    setLabel(formatRelativeTime(iso))
    const id = setInterval(() => setLabel(formatRelativeTime(iso)), 15000)
    return () => clearInterval(id)
  }, [iso])
  return label
}
