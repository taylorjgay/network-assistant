import { useState, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Toaster } from '@/components/ui/sonner'
import { ThemeToggle } from '@/components/ThemeToggle'
import { RefreshButton } from '@/components/RefreshButton'
import OverviewPage from '@/pages/OverviewPage'
import NetworkPage from '@/pages/NetworkPage'
import DnsPage from '@/pages/DnsPage'
import FirewallPage from '@/pages/FirewallPage'

export default function App() {
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
      <Tabs defaultValue="overview">
        <header className="sticky top-0 z-10 border-b border-border bg-background px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <span className="font-bold text-base">🛜 Network Assistant</span>
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="network">Network</TabsTrigger>
              <TabsTrigger value="dns">DNS</TabsTrigger>
              <TabsTrigger value="firewall">Firewall</TabsTrigger>
            </TabsList>
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
          <TabsContent value="overview"><OverviewPage /></TabsContent>
          <TabsContent value="network"><NetworkPage /></TabsContent>
          <TabsContent value="dns"><DnsPage /></TabsContent>
          <TabsContent value="firewall"><FirewallPage /></TabsContent>
        </main>
      </Tabs>
    </div>
  )
}
