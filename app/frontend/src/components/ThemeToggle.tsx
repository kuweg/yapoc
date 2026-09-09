import { Moon as MoonIcon, Sun as SunIcon, Palette as SwatchIcon } from 'lucide-react'
import { useThemeStore } from '../store/themeStore'

interface Props { variant?: 'icon' | 'full'; className?: string }
const nextLabels = { dark: 'Switch to light theme', light: 'Switch to warm theme', claude: 'Switch to dark theme' }
export function ThemeToggle({ variant = 'icon', className = '' }: Props) {
  const theme = useThemeStore(s => s.theme)
  const toggleTheme = useThemeStore(s => s.toggleTheme)
  const Icon = theme === 'dark' ? SunIcon : theme === 'light' ? SwatchIcon : MoonIcon
  return <button onClick={toggleTheme} aria-label={nextLabels[theme]} title={nextLabels[theme]} className={`studio-icon-button ${className}`}>
    <Icon />{variant === 'full' && <span>{nextLabels[theme]}</span>}
  </button>
}
