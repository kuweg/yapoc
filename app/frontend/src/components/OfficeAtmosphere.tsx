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
  const furniture: Record<string, React.ReactNode> = {
    study: <g><path d="M193 55h35v44h-35z" fill="#624b40" /><path d="M196 58h29v10h-29zm0 14h29v10h-29zm0 14h29v10h-29z" fill="#a3875c" /><path d="M208 62h6v2h-6zm0 14h6v2h-6zm0 14h6v2h-6z" fill="#423a32" /></g>,
    workshop: <g><path d="M192 59h36v40h-36z" fill="#4c646b" /><path d="M195 62h30v12h-30z" fill="#172c32" /><path d="M197 64h7v2h-7zm0 4h18v2h-18z" fill="#9ad4af" /><path d="M195 79h30v3h-30zm0 7h30v3h-30z" fill="#92a19e" /><path d="M195 94h3v2h-3zm6 0h3v2h-3z" fill="#d6b968" /></g>,
    library: <g><path d="M192 49h37v51h-37z" fill="#8d6848" /><path d="M195 52h31v18h-31zm0 22h31v21h-31z" fill="#342d29" /><path d="M197 54h5v16h-5zm14 23h5v18h-5z" fill="#a0a777" /><path d="M204 57h6v13h-6zm-7 19h5v19h-5z" fill="#b97860" /><path d="M212 53h6v17h-6zm7 27h5v15h-5z" fill="#7c99a6" /></g>,
    greenhouse: <g><path d="M198 83h24v16h-24z" fill="#ad7656" /><path d="M209 46h3v38h-3z" fill="#87a56f" /><path d="M197 49h12v9h-12zm15 10h15v9h-15zm-21 9h18v9h-18zm21-25h10v10h-10z" fill="#73955d" /></g>,
    clinic: <g><path d="M195 53h32v46h-32z" fill="#bac8bb" /><path d="M198 56h26v22h-26z" fill="#52776f" /><path d="M207 59h7v4h4v7h-4v4h-7v-4h-4v-7h4z" fill="#d0d8bb" /><path d="M198 82h26v2h-26zm10 7h6v2h-6z" fill="#6b8b83" /></g>,
    studio: <g><path d="M207 49h3v45h-3zm-9 45h3v6h-3zm20 0h3v6h-3z" fill="#ad8960" /><path d="M193 56h34v32h-34z" fill="#d8c4a2" /><path d="M197 60h13v11h-13z" fill="#ae7f89" /><path d="M206 72h16v12h-16z" fill="#80a6a2" /><path d="M193 88h35v4h-35z" fill="#977251" /></g>,
  }
  return <svg className="office-specialty" viewBox="0 0 240 110" preserveAspectRatio="none" aria-hidden="true" shapeRendering="crispEdges">{art[theme]}{furniture[theme]}</svg>
}

export function OfficePet({ sleeping, role }: { sleeping: boolean; role: string }) {
  const coats: Record<string, string[]> = { study: ['#d5c9af', '#7c756e'], workshop: ['#cb8c55', '#865435'], library: ['#808d9d', '#c4ccd2'], greenhouse: ['#ddd1b3', '#a47755'], clinic: ['#e4e1d4', '#a6afb0'], studio: ['#726573', '#d6b6a2'] }
  const [coat, patch] = coats[officeTheme(role)]
  return <svg className={`office-pet ${sleeping ? 'is-sleeping' : ''}`} viewBox="0 0 24 16" shapeRendering="crispEdges" aria-hidden="true">
    <path d={sleeping ? 'M4 9h15v5H4zM14 6h2v2h4V6h2v7h-8z' : 'M4 7h12v6H4zM13 3h2v2h5V3h2v8h-9zM5 13h3v2H5zm7 0h3v2h-3z'} fill={coat} />
    <path d="M7 9h3v3H7zm4 0h2v2h-2z" fill={patch} />
    <path className="office-pet-tail" d="M2 4h2v6h3v3H2z" fill={coat} />
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
