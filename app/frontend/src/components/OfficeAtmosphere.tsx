import { useEffect, useRef, useState } from 'react'

const themes = ['study', 'workshop', 'library', 'greenhouse', 'clinic', 'studio'] as const
export function officeTheme(role: string) {
  const known: Record<string, typeof themes[number]> = { master: 'study', builder: 'workshop', researcher: 'library', keeper: 'greenhouse', doctor: 'clinic', evaluator: 'studio' }
  return known[role] || themes[Array.from(role).reduce((sum, c) => sum + c.charCodeAt(0), 0) % themes.length]
}

export function OfficeFurnishing({ role }: { role: string }) {
  const theme = officeTheme(role)
  const art: Record<string, React.ReactNode> = {
    study: <><path d="M14 12h44v24H14z" fill="#8c7354" /><path d="M17 15h38v18H17z" fill="#bfaf82" /><path d="M20 19h12v2H20zm17 0h13v2H37zm-14 7h23v2H23z" fill="#6c866f" /></>,
    workshop: <><path d="M14 12h44v24H14z" fill="#665d48" /><path d="M19 17h4v12h-4zm-3 0h10v3H16zm19 0h5v5h-5zm2 5h2v9h-2zm10-5h4v13h-4z" fill="#b5bdad" /></>,
    library: <><path d="M14 10h46v30H14z" fill="#866747" /><path d="M17 13h40v10H17zm0 14h40v10H17z" fill="#302b27" /><path d="M19 14h5v9h-5zm14 0h4v9h-4zm10 14h5v9h-5z" fill="#bd956e" /><path d="M26 16h5v7h-5zm14-3h5v10h-5zm-19 16h6v8h-6z" fill="#7d9c94" /></>,
    greenhouse: <><path d="M15 30h44v4H15z" fill="#987756" /><path d="M20 23h9v7h-9zm20-3h11v10H40z" fill="#b98468" /><path d="M24 12h3v11h-3zm-7 2h7v5h-7zm10-4h7v6h-7zm17 0h3v10h-3zm-7 0h7v5h-7zm10 3h8v5h-8z" fill="#89a56a" /></>,
    clinic: <><path d="M16 12h42v25H16z" fill="#88a49b" /><path d="M19 15h36v19H19z" fill="#294342" /><path d="M22 25h7v-6h3v12h3v-6h17" fill="none" stroke="#a4d2af" strokeWidth="2" /></>,
    studio: <><path d="M15 12h44v25H15z" fill="#817089" /><path d="M18 15h38v19H18z" fill="#bfb199" /><path d="M23 19h8v9h-8z" fill="#769991" /><path d="M35 18h15v3H35zm0 6h11v3H35z" fill="#946f7e" /></>,
  }
  return <svg className="office-specialty" viewBox="0 0 240 110" preserveAspectRatio="none" aria-hidden="true" shapeRendering="crispEdges">{art[theme]}</svg>
}

export function OfficePet({ sleeping }: { sleeping: boolean }) {
  return <svg className={`office-pet ${sleeping ? 'is-sleeping' : ''}`} viewBox="0 0 24 16" shapeRendering="crispEdges" aria-hidden="true">
    <path d={sleeping ? 'M4 9h15v5H4zM14 6h2v2h4V6h2v7h-8z' : 'M4 7h12v6H4zM13 3h2v2h5V3h2v8h-9zM5 13h3v2H5zm7 0h3v2h-3z'} fill="#bf996f" />
    <path className="office-pet-tail" d="M2 4h2v6h3v3H2z" fill="#bf996f" />
    <path d={sleeping ? 'M16 10h2v1h-2z' : 'M17 7h1v1h-1zm3 0h1v1h-1z'} fill="#382e28" />
  </svg>
}

// Animate newly observed work, never replay the initial status snapshot as a delivery.
export function OfficeDelivery({ signature, connected }: { signature: string; connected: boolean }) {
  const previous = useRef(signature)
  const wasConnected = useRef(connected)
  const [delivery, setDelivery] = useState(0)
  useEffect(() => {
    if (connected && wasConnected.current && signature && previous.current !== signature) setDelivery(n => n + 1)
    previous.current = signature
    wasConnected.current = connected
  }, [signature, connected])
  return delivery > 0 && connected ? <span key={delivery} className="office-delivery" aria-hidden="true">✉</span> : null
}
