import { useThemeStore } from '../store/themeStore'

interface Props {
  /** Visual style variant — 'icon' shows just the icon, 'full' shows icon + label */
  variant?: 'icon' | 'full'
  /** Extra CSS classes */
  className?: string
}

export function ThemeToggle({ variant: _variant = 'icon', className = '' }: Props) {
  const { theme, toggleTheme } = useThemeStore()
  const isDark = theme === 'dark'

  return (
    <button
      onClick={toggleTheme}
      aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
      title={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
      className={[
        'px-2 py-1 text-xs font-mono tracking-widest transition-colors',
        'border',
        isDark
          ? 'bg-transparent border-[#2a2a1a] text-[#606050] hover:text-[#FFB633] hover:border-[#FFB633]'
          : 'bg-transparent border-[#c8c0a8] text-[#8a8a7a] hover:text-[#8a6010] hover:border-[#8a6010]',
        className,
      ].join(' ')}
    >
      {isDark ? '[LITE]' : '[DARK]'}
    </button>
  )
}
