import { useEffect, useState, useMemo } from 'react'
import { useSessionStore } from '../store/session'
import { useAppStore } from '../store/appStore'
import { getChannelSessions, getChannelSessionMessages } from '../api/client'
import type { ChannelInfo, SessionInfo } from '../api/types'

type ViewState = 'loading' | 'error' | 'channels' | 'sessions' | 'messages'

export function ChannelsDashboard() {
  const [viewState, setViewState] = useState<ViewState>('loading')
  const [channels, setChannels] = useState<ChannelInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [selectedChannel, setSelectedChannel] = useState<ChannelInfo | null>(null)
  const [selectedSession, setSelectedSession] = useState<SessionInfo | null>(null)
  const [loadingMessages, setLoadingMessages] = useState(false)

  const loadSession = useSessionStore((s) => s.loadSession)
  const newSession = useSessionStore((s) => s.newSession)
  const appendMessage = useSessionStore((s) => s.appendMessage)
  const setActiveTab = useAppStore((s) => s.setActiveTab)
  const sessions = useSessionStore((s) => s.sessions)

  useEffect(() => {
    loadChannels()
  }, [])

  async function loadChannels() {
    setViewState('loading')
    setError(null)
    try {
      const data = await getChannelSessions()
      setChannels(data.channels)
      setViewState('channels')
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
      setViewState('error')
    }
  }

  function handleChannelClick(channel: ChannelInfo) {
    setSelectedChannel(channel)
    setSelectedSession(null)
    setViewState('sessions')
  }

  async function handleSessionClick(session: SessionInfo) {
    setSelectedSession(session)
    setLoadingMessages(true)
    try {
      const data = await getChannelSessionMessages(session.source, session.id)
      // Create a local session entry with the loaded messages
      const id = crypto.randomUUID()
      const localSession = {
        id,
        name: session.name || `Session from ${session.source}`,
        createdAt: session.createdAt || new Date().toISOString(),
        history: data.messages,
        source: session.source,
      }
      // Add to store and navigate to chat
      useSessionStore.setState((s) => ({
        sessions: [localSession, ...s.sessions].slice(0, 50),
        activeId: id,
        history: data.messages,
      }))
      setActiveTab('chat')
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setLoadingMessages(false)
    }
  }

  function handleBack() {
    if (selectedSession) {
      setSelectedSession(null)
      setViewState('sessions')
    } else if (selectedChannel) {
      setSelectedChannel(null)
      setViewState('channels')
    }
  }

  function fmtDate(iso: string): string {
    if (!iso) return ''
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString()
  }

  // ── Loading state ──
  if (viewState === 'loading') {
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500 text-sm font-mono">
        Loading channels…
      </div>
    )
  }

  // ── Error state ──
  if (viewState === 'error') {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6 py-4">
        <div className="px-3 py-2 border border-red-700 bg-red-950/50 text-red-300 text-xs font-mono max-w-lg">
          {error || 'Failed to load channels'}
        </div>
        <button
          onClick={loadChannels}
          className="px-3 py-1 text-xs font-mono uppercase tracking-wider border border-zinc-700 text-zinc-300 hover:text-[#FFB633] hover:border-[#FFB633]"
        >
          Retry
        </button>
      </div>
    )
  }

  // ── Sessions list for a channel ──
  if (viewState === 'sessions' && selectedChannel) {
    return (
      <div className="flex-1 overflow-y-auto bg-zinc-950 text-zinc-100 px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-center gap-3 mb-4">
            <button
              onClick={handleBack}
              className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-400 hover:text-[#FFB633] hover:border-[#FFB633]"
            >
              ← Back
            </button>
            <h2 className="font-mono text-xs uppercase tracking-widest text-[#FFB633]">
              {selectedChannel.source} ({selectedChannel.count})
            </h2>
          </div>

          {selectedChannel.sessions.length === 0 ? (
            <div className="text-zinc-500 text-sm font-mono">No sessions found for this channel.</div>
          ) : (
            <ul className="space-y-2">
              {selectedChannel.sessions.map((s) => (
                <li
                  key={s.id}
                  className="flex items-center gap-3 px-3 py-2 border border-zinc-800 bg-zinc-900 hover:border-zinc-600 cursor-pointer transition-colors"
                  onClick={() => handleSessionClick(s)}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-mono truncate text-zinc-200">
                      {s.name || '(unnamed)'}
                    </div>
                    <div className="text-[11px] text-zinc-500 font-mono">
                      {s.messageCount} msg{s.messageCount === 1 ? '' : 's'} · {fmtDate(s.createdAt)}
                    </div>
                    {s.preview && (
                      <div className="text-[11px] text-zinc-600 font-mono truncate mt-1">
                        {s.preview}
                      </div>
                    )}
                  </div>
                  <span className="text-[11px] font-mono text-[#FFB633] uppercase tracking-wider">
                    Open →
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    )
  }

  // ── Channel cards grid ──
  return (
    <div className="flex-1 overflow-y-auto bg-zinc-950 text-zinc-100 px-6 py-4">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <h2 className="font-mono text-xs uppercase tracking-widest text-[#FFB633]">
            Channel Dashboard
          </h2>
          <button
            onClick={loadChannels}
            className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-400 hover:text-[#FFB633] hover:border-[#FFB633]"
          >
            Refresh
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {channels.map((channel) => (
            <div
              key={channel.source}
              onClick={() => handleChannelClick(channel)}
              className="border border-zinc-800 bg-zinc-900 p-4 cursor-pointer hover:border-[#FFB633]/50 transition-colors"
            >
              <div className="flex items-center justify-between mb-3">
                <span className="font-mono text-sm uppercase tracking-wider text-[#FFB633]">
                  {channel.source}
                </span>
                <span className="font-mono text-2xl font-bold text-zinc-100">
                  {channel.count}
                </span>
              </div>
              <div className="text-[11px] font-mono text-zinc-500">
                {channel.count === 1 ? '1 session' : `${channel.count} sessions`}
              </div>
              {channel.sessions.length > 0 && (
                <div className="mt-2 text-[11px] font-mono text-zinc-600 truncate">
                  Latest: {channel.sessions[0].name || '(unnamed)'}
                </div>
              )}
            </div>
          ))}
        </div>

        {channels.length === 0 && (
          <div className="text-zinc-500 text-sm font-mono text-center py-12">
            No channels found. Start a conversation to see it here.
          </div>
        )}
      </div>
    </div>
  )
}
