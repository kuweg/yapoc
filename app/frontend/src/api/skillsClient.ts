export interface Skill {
  name: string
  summary?: string | null
  description?: string | null
  levels: string[]
}

export interface SkillDraft {
  summary?: string | null
  description?: string | null
  level_1?: string | null
  level_2?: string | null
  level_3?: string | null
}

export async function getSkills(): Promise<Skill[]> {
  const res = await fetch(`/api/skills`)
  if (!res.ok) throw new Error(`skills: ${res.status}`)
  return res.json() as Promise<Skill[]>
}

export async function createSkill(name: string, content: SkillDraft): Promise<Skill> {
  const res = await fetch(`/api/skills`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, ...content }),
  })
  if (!res.ok) throw new Error(`createSkill: ${res.status}`)
  return res.json() as Promise<Skill>
}

export async function updateSkill(name: string, content: SkillDraft): Promise<Skill> {
  const res = await fetch(`/api/skills/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, ...content }),
  })
  if (!res.ok) throw new Error(`updateSkill: ${res.status}`)
  return res.json() as Promise<Skill>
}

export async function deleteSkill(name: string): Promise<void> {
  const res = await fetch(`/api/skills/${encodeURIComponent(name)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`deleteSkill: ${res.status}`)
}
