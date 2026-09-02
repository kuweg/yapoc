import { useEffect, useState, useCallback } from 'react'
import { getSkills, createSkill, deleteSkill, updateSkill, type Skill, type SkillDraft } from '../api/skillsClient'

const inputClass =
  'w-full bg-zinc-900 text-zinc-100 text-sm border border-zinc-800 rounded px-3 py-2 focus:outline-none focus:ring-1 focus:ring-zinc-600 placeholder-zinc-600'

export function SkillsTab() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // editor state
  const [editorName, setEditorName] = useState<string | null>(null)
  const [draft, setDraft] = useState<SkillDraft>({})

  // create state
  const [showCreate, setShowCreate] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createDraft, setCreateDraft] = useState<SkillDraft>({})

  // delete confirm
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    getSkills()
      .then(setSkills)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const Field = ({
    label,
    value,
    onChange,
    textarea,
  }: {
    label: string
    value: string
    onChange: (v: string) => void
    textarea?: boolean
  }) => (
    <label className="block">
      <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">{label}</span>
      {textarea ? (
        <textarea
          className={inputClass + ' resize-y min-h-[64px]'}
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          className={inputClass}
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </label>
  )

  const openEditor = (skill: Skill) => {
    setDraft({
      summary: skill.summary ?? null,
      description: skill.description ?? null,
      level_1: null,
      level_2: null,
      level_3: null,
    })
    setEditorName(skill.name)
  }

  const saveEdit = async () => {
    if (!editorName) return
    try {
      await updateSkill(editorName, draft)
      setEditorName(null)
      setDraft({})
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'update failed')
    }
  }

  const submitCreate = async () => {
    if (!createName.trim()) return
    // Backend requires at minimum name + level_1 to create a skill.
    if (!createDraft.level_1 || !createDraft.level_1.trim()) {
      setError('Level 1 content is required to create a skill.')
      return
    }
    try {
      await createSkill(createName.trim(), createDraft)
      setShowCreate(false)
      setCreateName('')
      setCreateDraft({})
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'create failed')
    }
  }

  const doDelete = async (name: string) => {
    try {
      await deleteSkill(name)
      setConfirmDelete(null)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'delete failed')
    }
  }

  return (
    <div className="relative flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-4 px-4 py-3 border-b border-zinc-800 flex-shrink-0">
        <h2 className="text-xs uppercase tracking-widest text-zinc-500">Skills</h2>
        <span className="text-zinc-500 text-xs">app/skills/</span>
        {error && <span className="text-red-400 text-xs">{error}</span>}
        <div className="flex-1" />
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="text-xs text-zinc-400 hover:text-[#FFB633] transition-colors border border-zinc-800 rounded px-2 py-1"
          title="New skill"
        >
          + New skill
        </button>
        <button
          onClick={load}
          className="text-zinc-400 hover:text-zinc-300 text-sm transition-colors"
          title="Refresh skills"
        >
          ↻
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="border-b border-zinc-800 p-4 space-y-3 bg-zinc-900/50 flex-shrink-0">
          <Field label="Name" value={createName} onChange={(v) => setCreateName(v)} />
          <Field label="Summary" value={createDraft.summary ?? ''} onChange={(v) => setCreateDraft((d) => ({ ...d, summary: v }))} textarea />
          <Field label="Description" value={createDraft.description ?? ''} onChange={(v) => setCreateDraft((d) => ({ ...d, description: v }))} textarea />
          <Field label="Level 1" value={createDraft.level_1 ?? ''} onChange={(v) => setCreateDraft((d) => ({ ...d, level_1: v }))} textarea />
          <Field label="Level 2" value={createDraft.level_2 ?? ''} onChange={(v) => setCreateDraft((d) => ({ ...d, level_2: v }))} textarea />
          <Field label="Level 3" value={createDraft.level_3 ?? ''} onChange={(v) => setCreateDraft((d) => ({ ...d, level_3: v }))} textarea />
          <div className="flex gap-2">
            <button
              onClick={submitCreate}
              disabled={!createName.trim() || !(createDraft.level_1 && createDraft.level_1.trim())}
              className="px-3 py-1.5 text-xs rounded bg-[#FFB633] text-zinc-900 font-medium disabled:opacity-40"
            >
              Create
            </button>
            <button
              onClick={() => { setShowCreate(false); setCreateName(''); setCreateDraft({}) }}
              className="px-3 py-1.5 text-xs rounded border border-zinc-800 text-zinc-400 hover:text-zinc-200"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto min-h-0 p-4 space-y-3">
        {loading ? (
          <div className="px-4 py-4 text-zinc-400 text-sm animate-pulse">loading…</div>
        ) : skills.length === 0 ? (
          <div className="px-4 py-4 text-zinc-400 text-sm">No skills found.</div>
        ) : (
          skills.map((skill) => (
            <div key={skill.name} className="border border-zinc-800 bg-zinc-900 p-3 rounded">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-mono text-sm text-zinc-100">{skill.name}</span>
                {skill.levels.map((level) => {
                  const num = level.replace('level_', '')
                  return (
                    <span
                      key={level}
                      className="px-1.5 py-0.5 text-[10px] font-mono rounded border border-[#FFB633]/40 text-[#FFB633]"
                    >
                      L{num}
                    </span>
                  )
                })}
                <div className="flex-1" />
                <button
                  onClick={() => openEditor(skill)}
                  className="text-[11px] text-zinc-400 hover:text-zinc-200 transition-colors"
                >
                  edit
                </button>
                <button
                  onClick={() => setConfirmDelete(skill.name)}
                  className="text-[11px] text-zinc-400 hover:text-red-400 transition-colors"
                >
                  delete
                </button>
              </div>
              {skill.summary && (
                <p className="text-sm text-zinc-400 mb-1">{skill.summary}</p>
              )}
              {skill.description && (
                <pre className="text-xs text-zinc-400 whitespace-pre-wrap font-mono border-t border-zinc-800 pt-2 mt-2">
                  {skill.description}
                </pre>
              )}

              {/* Delete confirm */}
              {confirmDelete === skill.name && (
                <div className="mt-3 border border-red-800/50 bg-red-950/30 rounded p-3 space-y-2">
                  <p className="text-xs text-zinc-300">
                    Delete &quot;{skill.name}&quot;? This cannot be undone.
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => doDelete(skill.name)}
                      className="px-3 py-1.5 text-xs rounded bg-red-600 text-white font-medium"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setConfirmDelete(null)}
                      className="px-3 py-1.5 text-xs rounded border border-zinc-800 text-zinc-400 hover:text-zinc-200"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Editor overlay */}
      {editorName !== null && (
        <div className="absolute inset-0 z-20 bg-zinc-950/80 flex items-center justify-center p-4">
          <div className="w-full max-w-lg border border-zinc-800 bg-zinc-900 rounded p-4 space-y-3 max-h-full overflow-y-auto">
            <h3 className="text-sm font-medium text-zinc-100">{editorName}</h3>
            <p className="text-xs text-zinc-500">
              Level content is blank — only summary/description are reliably pre-filled from the API.
            </p>
            <Field label="Summary" value={draft.summary ?? ''} onChange={(v) => setDraft((d) => ({ ...d, summary: v }))} textarea />
            <Field label="Description" value={draft.description ?? ''} onChange={(v) => setDraft((d) => ({ ...d, description: v }))} textarea />
            <Field label="level_1" value={draft.level_1 ?? ''} onChange={(v) => setDraft((d) => ({ ...d, level_1: v }))} textarea />
            <Field label="level_2" value={draft.level_2 ?? ''} onChange={(v) => setDraft((d) => ({ ...d, level_2: v }))} textarea />
            <Field label="level_3" value={draft.level_3 ?? ''} onChange={(v) => setDraft((d) => ({ ...d, level_3: v }))} textarea />
            <div className="flex gap-2">
              <button
                onClick={saveEdit}
                className="px-3 py-1.5 text-xs rounded bg-[#FFB633] text-zinc-900 font-medium"
              >
                Save
              </button>
              <button
                onClick={() => { setEditorName(null); setDraft({}) }}
                className="px-3 py-1.5 text-xs rounded border border-zinc-800 text-zinc-400 hover:text-zinc-200"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
