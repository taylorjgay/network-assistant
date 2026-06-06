import { useState } from 'react'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import type {
  SpeedtestResult, WANHealthCompare, WANSpeedCompare, GravityResult,
  PingResult, TracerouteResult, DnsLookupResult,
} from '@/lib/types'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'

type ToolState<T> = null | 'running' | T

async function runTool<T>(
  setter: (s: ToolState<T>) => void,
  fn: () => Promise<T>,
) {
  setter('running')
  try {
    setter(await fn())
  } catch {
    setter({ success: false, error: 'Request failed' } as T)
  }
}

function ResultBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-2 rounded-md border border-border bg-muted/40 p-3 text-xs font-mono space-y-1">
      {children}
    </div>
  )
}

function ErrorLine({ error, suggestion }: { error?: string; suggestion?: string }) {
  return (
    <>
      <div className="text-red-400">{error ?? 'Unknown error'}</div>
      {suggestion && <div className="text-muted-foreground">{suggestion}</div>}
    </>
  )
}

function SpeedtestCard() {
  const [result, setResult] = useState<ToolState<SpeedtestResult>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Speed Test</span>
        <Button
          size="sm"
          className="h-7 text-xs"
          disabled={result === 'running'}
          onClick={() => runTool(setResult, api.speedtest)}
        >
          {result === 'running' ? 'Running…' : 'Run'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success ? (
            <>
              <div className="text-green-400">↓ {result.download_mbps} Mbps &nbsp; ↑ {result.upload_mbps} Mbps &nbsp; ping {result.ping_ms} ms</div>
              {result.server && <div className="text-muted-foreground">{result.server} — {result.server_location}</div>}
            </>
          ) : <ErrorLine error={result.error} suggestion={result.suggestion} />}
        </ResultBox>
      )}
    </div>
  )
}

function WANHealthCompareCard() {
  const [result, setResult] = useState<ToolState<WANHealthCompare>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Compare WAN Health</span>
        <Button
          size="sm"
          className="h-7 text-xs"
          disabled={result === 'running'}
          onClick={() => runTool(setResult, () => api.compareWan() as Promise<WANHealthCompare>)}
        >
          {result === 'running' ? 'Running…' : 'Run'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success ? (
            <>
              {result.wan1_probe && <div>WAN1: {result.wan1_probe.avg_latency_ms}ms · {result.wan1_probe.packet_loss_pct}% loss{result.wan1_probe.degraded ? ' ⚠ degraded' : ''}</div>}
              {result.wan2_probe && <div>WAN2: {result.wan2_probe.avg_latency_ms}ms · {result.wan2_probe.packet_loss_pct}% loss{result.wan2_probe.degraded ? ' ⚠ degraded' : ''}</div>}
              {result.recommendation && <div className="text-green-400 mt-1">{result.recommendation}</div>}
            </>
          ) : <ErrorLine error={result.error} />}
        </ResultBox>
      )}
    </div>
  )
}

function WANSpeedCompareCard() {
  const [quick, setQuick] = useState(true)
  const [result, setResult] = useState<ToolState<WANSpeedCompare>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium">Compare WAN Speed</span>
          <div className="flex items-center gap-1.5">
            <Switch
              checked={!quick}
              onCheckedChange={v => setQuick(!v)}
              disabled={result === 'running'}
            />
            <Label className="text-xs text-muted-foreground">{quick ? 'Quick' : 'Full'}</Label>
          </div>
        </div>
        <Button
          size="sm"
          className="h-7 text-xs"
          disabled={result === 'running'}
          onClick={() => runTool(setResult, () => api.compareWanSpeed(quick))}
        >
          {result === 'running' ? 'Running…' : 'Run'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success ? (
            <>
              {result.wan1 && <div>WAN1: {result.quick ? `${result.wan1.latency_ms}ms latency` : `↓${result.wan1.download_mbps} ↑${result.wan1.upload_mbps} Mbps · ${result.wan1.latency_ms}ms`}</div>}
              {result.wan2 && <div>WAN2: {result.quick ? `${result.wan2.latency_ms}ms latency` : `↓${result.wan2.download_mbps} ↑${result.wan2.upload_mbps} Mbps · ${result.wan2.latency_ms}ms`}</div>}
              {result.recommendation && <div className="text-green-400 mt-1">{result.recommendation}</div>}
            </>
          ) : <ErrorLine error={result.error} />}
        </ResultBox>
      )}
    </div>
  )
}

function GravityCard() {
  const [result, setResult] = useState<ToolState<GravityResult>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Update Pi-hole Gravity</span>
        <Button
          size="sm"
          className="h-7 text-xs"
          disabled={result === 'running'}
          onClick={() => runTool(setResult, api.updateGravity)}
        >
          {result === 'running' ? 'Running…' : 'Run'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success
            ? <div className="text-green-400">{result.message}</div>
            : <ErrorLine error={result.error} />}
        </ResultBox>
      )}
    </div>
  )
}

function PingCard() {
  const [host, setHost] = useState('8.8.8.8')
  const [result, setResult] = useState<ToolState<PingResult>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium w-24 shrink-0">Ping</span>
        <Input
          className="h-7 text-xs font-mono"
          value={host}
          onChange={e => setHost(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && host.trim() && runTool(setResult, () => api.ping(host.trim()))}
          placeholder="host or IP"
        />
        <Button
          size="sm"
          className="h-7 text-xs shrink-0"
          disabled={result === 'running' || !host.trim()}
          onClick={() => runTool(setResult, () => api.ping(host.trim()))}
        >
          {result === 'running' ? '…' : 'Go'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success
            ? <div className={result.reachable ? 'text-green-400' : 'text-red-400'}>
                {result.reachable ? `${result.avg_ms}ms avg · ${result.packet_loss_pct}% loss` : `Unreachable — ${result.packet_loss_pct}% loss`}
              </div>
            : <ErrorLine error={result.error} suggestion={result.suggestion} />}
        </ResultBox>
      )}
    </div>
  )
}

function TracerouteCard() {
  const [host, setHost] = useState('1.1.1.1')
  const [result, setResult] = useState<ToolState<TracerouteResult>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium w-24 shrink-0">Traceroute</span>
        <Input
          className="h-7 text-xs font-mono"
          value={host}
          onChange={e => setHost(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && host.trim() && runTool(setResult, () => api.traceroute(host.trim()))}
          placeholder="host or IP"
        />
        <Button
          size="sm"
          className="h-7 text-xs shrink-0"
          disabled={result === 'running' || !host.trim()}
          onClick={() => runTool(setResult, () => api.traceroute(host.trim()))}
        >
          {result === 'running' ? '…' : 'Go'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success ? (
            result.hops.length === 0
              ? <div className="text-muted-foreground">No hops recorded</div>
              : result.hops.map(h => (
                  <div key={h.hop}>
                    <span className="text-muted-foreground w-5 inline-block">{h.hop}</span>
                    {h.timeout ? <span className="text-muted-foreground">* * *</span> : (
                      <><span className="text-foreground">{h.ip}</span><span className="text-muted-foreground ml-2">{h.ms}ms</span></>
                    )}
                  </div>
                ))
          ) : <ErrorLine error={result.error} suggestion={result.suggestion} />}
        </ResultBox>
      )}
    </div>
  )
}

function DnsLookupCard() {
  const [hostname, setHostname] = useState('')
  const [result, setResult] = useState<ToolState<DnsLookupResult>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium w-24 shrink-0">DNS Lookup</span>
        <Input
          className="h-7 text-xs font-mono"
          value={hostname}
          onChange={e => setHostname(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && hostname.trim() && runTool(setResult, () => api.dnsLookup(hostname.trim()))}
          placeholder="hostname"
        />
        <Button
          size="sm"
          className="h-7 text-xs shrink-0"
          disabled={result === 'running' || !hostname.trim()}
          onClick={() => runTool(setResult, () => api.dnsLookup(hostname.trim()))}
        >
          {result === 'running' ? '…' : 'Go'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success ? (
            <>
              {result.addresses?.map((a, i) => <div key={i} className="text-green-400">{a}</div>)}
              <div className="text-muted-foreground">via {result.dns_server} · {result.elapsed_ms}ms</div>
            </>
          ) : <ErrorLine error={result.error} suggestion={result.suggestion} />}
        </ResultBox>
      )}
    </div>
  )
}

export default function DiagnosticsPage() {
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium mb-3">Quick Actions</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <SpeedtestCard />
          <WANHealthCompareCard />
          <WANSpeedCompareCard />
          <GravityCard />
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium mb-3">Lookups</h3>
        <div className="space-y-3">
          <PingCard />
          <TracerouteCard />
          <DnsLookupCard />
        </div>
      </div>
    </div>
  )
}
