import { useThemeStore } from '../store/themeStore'

interface Props {
  /** Visual style variant — 'icon' shows just the icon, 'full' shows icon + label */
  variant?: 'icon' | 'full'
  /** Extra CSS classes */
  className?: string
}

const themeLabels: Record<string, string> = {
  dark: '[LITE]',
  light: '[DARK]',
  claude: '[CLAUDE]',
}

const themeStyles: Record<string, string> = {
  dark: 'bg-transparent border-[#2a2a1a] text-[#606050] hover:text-[#FFB633] hover:border-[#FFB633]',
  light: 'bg-transparent border-[#c8c0a8] text-[#8a8a7a] hover:text-[#8a6010] hover:border-[#8a6010]',
  claude: 'bg-transparent border-[#d4d0c8] text-[#b1ada1] hover:text-[#c15f3c] hover:border-[#c15f3c]',
}

const themeAriaLabels: Record<string, string> = {
  dark: 'Switch to light theme',
  light: 'Switch to claude theme',
  claude: 'Switch to dark theme',
}

export function ThemeToggle({ variant: _variant = 'icon', className = '' }: Props) {
  const { theme, toggleTheme } = useThemeStore()

  return (
    <button
      onClick={toggleTheme}
      aria-label={themeAriaLabels[theme]}
      title={themeAriaLabels[theme]}
      className={[
        'px-2 py-1 text-xs font-mono tracking-widest transition-colors',
        'border',
        themeStyles[theme],
        className,
      ].join(' ')}
    >
      {themeLabels[theme]}
    </button>
  )
}
