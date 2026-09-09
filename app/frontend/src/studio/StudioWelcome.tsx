import { ArrowUpRight, Code, Search, FolderSearch } from 'lucide-react'
import { YapocMark } from './StudioNavigation'

const STARTERS = [
  { title: 'Build or fix something', text: 'Explore a project and make a focused change.', icon: Code,
    prompt: 'Help me build a feature in my project. First, explore the workspace and ask me what I want to create.' },
  { title: 'Research a problem', text: 'Investigate a question and produce a clear report.', icon: Search,
    prompt: 'Help me research a topic and turn the findings into a clear report. Ask me about the topic and the questions I want answered.' },
  { title: 'Explore the workspace', text: 'Understand the files, structure, and next steps.', icon: FolderSearch,
    prompt: 'Help me understand my workspace. Review the files and explain the project structure without making changes.' },
]

export function StudioWelcome({ onChoose }: { onChoose: (prompt: string) => void }) {
  return <section className="studio-welcome" aria-label="Welcome to YAPOC">
    <div className="studio-welcome-identity"><YapocMark /><span>YAPOC <span>/</span> Multi-agent workspace</span></div>
    <h1>What are we working on?</h1>
    <p className="studio-welcome-description">One conversation with Master. The right agents, tools, and<br className="studio-desktop-break" /> context for the work ahead.</p>
    <div className="studio-agent-path" aria-label="Master coordinates planning, building and research">
      <span>Master</span><span aria-hidden="true">→</span><span>Planning</span><span>Builder</span><span>Researcher</span>
    </div>
    <div className="studio-starters" aria-label="Suggested starting points">
      {STARTERS.map(({ title, text, icon: Icon, prompt }) => <button key={title} onClick={() => onChoose(prompt)} className="studio-starter">
        <Icon className="studio-starter-icon" /><div><strong>{title}</strong><span>{text}</span></div><ArrowUpRight className="studio-starter-arrow" />
      </button>)}
    </div>
    <p className="studio-welcome-note">Choose a starting point to edit, or write your own task below.</p>
  </section>
}
