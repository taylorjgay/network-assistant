import { useState, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/sonner'
import { ThemeToggle } from '@/components/ThemeToggle'
import { RefreshButton } from '@/components/RefreshButton'
import OverviewPage from '@/pages/OverviewPage'
import NetworkPage from '@/pages/NetworkPage'
import DnsPage from '@/pages/DnsPage'
import FirewallPage from '@/pages/FirewallPage'
import { cn } from '@/lib/utils'

type Tab = 'overview' | 'network' | 'dns' | 'firewall'

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'network', label: 'Network' },
  { id: 'dns', label: 'DNS' },
  { id: 'firewall', label: 'Firewall' },
]

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (localStorage.getItem('theme') as 'dark' | 'light') || 'dark'
  )
  const queryClient = useQueryClient()

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('theme', theme)
  }, [theme])

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Toaster />
      <header className="sticky top-0 z-10 border-b border-border bg-background px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <span className="font-bold text-base whitespace-nowrap">🛜 Network Assistant</span>
          <nav className="flex gap-1">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  'px-3 py-1.5 text-sm rounded-md transition-colors',
                  activeTab === tab.id
                    ? 'bg-primary text-primary-foreground font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                )}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-1">
          <RefreshButton onRefresh={() => queryClient.invalidateQueries()} />
          <ThemeToggle
            theme={theme}
            onToggle={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
          />
        </div>
      </header>
      <main className="p-6">
        {activeTab === 'overview' && <OverviewPage />}
        {activeTab === 'network' && <NetworkPage />}
        {activeTab === 'dns' && <DnsPage />}
        {activeTab === 'firewall' && <FirewallPage />}
      </main>
    </div>
  )
}
