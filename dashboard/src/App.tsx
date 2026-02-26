import { useEffect, useState } from 'react'
import './App.css'
import { TopBar } from './components/TopBar'
import { ArdenColumn } from './components/ArdenColumn'
import { RouterCore } from './components/RouterCore'
import { BudgetPanel } from './components/BudgetPanel'
import { ActivityStream, type ActivityEntry } from './components/ActivityStream'
import { ContextBudgetController } from './components/ContextBudgetController'

interface HealthResponse {
  status: string
  uptime_seconds: number
  providers: Record<string, { daily_cost_estimate: number; monthly_cost_estimate: number }>
}

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [activity, setActivity] = useState<ActivityEntry[]>([])
  const [budgetConfig, setBudgetConfig] = useState<{ priority: 'low' | 'normal' | 'high'; summarizationEnabled: boolean}>(
    { priority: 'normal', summarizationEnabled: false },
  )
  const [latestRoute, setLatestRoute] = useState<{
    provider: string
    model: string
    intent: string
    priority: string
  } | null>(null)
  const [contextTokens, setContextTokens] = useState<{
    before: number | null
    after: number | null
  }>({ before: null, after: null })

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await fetch('http://127.0.0.1:8001/ui/health')
        if (!res.ok) return
        const data = (await res.json()) as HealthResponse
        setHealth(data)
      } catch {
        // ignore; keep previous state
      }
    }

    fetchHealth()
    const id = setInterval(fetchHealth, 5000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const fetchLogs = async () => {
      try {
        const kinds: Array<'requests' | 'errors' | 'context'> = ['requests', 'errors', 'context']
        const results = await Promise.all(
          kinds.map(async (k) => {
            const res = await fetch(`http://127.0.0.1:8001/ui/logs?type=${k}&limit=40`)
            if (!res.ok) return { type: k, lines: [] as string[] }
            return (await res.json()) as { type: typeof k; lines: string[] }
          }),
        )

        const now = new Date()
        const timeStr = now.toTimeString().slice(0, 8)

        const entries: ActivityEntry[] = []
        let lastRouteLine: string | null = null
        let lastContextLine: string | null = null

        for (const { type, lines } of results) {
          for (const line of lines) {
            const level: ActivityEntry['level'] =
              type === 'errors' ? 'ERROR' : type === 'context' ? 'WARN' : 'INFO'
            const source =
              type === 'requests' ? 'ROUTING' : type === 'context' ? 'CONTEXT' : 'ERRORS'

            entries.push({
              timestamp: timeStr,
              level,
              source,
              message: line,
            })

            if (type === 'requests') lastRouteLine = line
            if (type === 'context') lastContextLine = line
          }
        }

        // Keep only the most recent 100 entries for display
        setActivity(entries.slice(-100))

        // Try to parse latest routing decision from the last requests log line
        if (lastRouteLine) {
          try {
            const jsonish = lastRouteLine.replace(/'/g, '"')
            const parsed = JSON.parse(jsonish)
            if (parsed && typeof parsed === 'object') {
              setLatestRoute({
                provider: String(parsed.provider ?? ''),
                model: String(parsed.model ?? ''),
                intent: String(parsed.intent ?? ''),
                priority: String(parsed.priority ?? ''),
              })
            }
          } catch {
            // ignore parse errors
          }
        }

        // Try to parse latest context info for token counts
        if (lastContextLine) {
          try {
            const jsonish = lastContextLine.replace(/'/g, '"')
            const parsed = JSON.parse(jsonish)
            if (parsed && typeof parsed === 'object') {
              const before = Number(parsed.estimated_prompt_tokens_before ?? NaN)
              const after = Number(parsed.estimated_prompt_tokens ?? NaN)
              setContextTokens({
                before: Number.isFinite(before) ? before : null,
                after: Number.isFinite(after) ? after : null,
              })
            }
          } catch {
            // ignore parse errors
          }
        }
      } catch {
        // ignore errors; preserve existing activity view
      }
    }

    fetchLogs()
    const id = setInterval(fetchLogs, 2500)
    return () => clearInterval(id)
  }, [])

  const providerSnapshot = health?.providers ?? undefined

  const ardenActivity = latestRoute
    ? [
        `Routing via ${latestRoute.provider}/${latestRoute.model}`,
        `Intent: ${latestRoute.intent || 'chat'}`,
        `Priority: ${latestRoute.priority || 'normal'}`,
        'Watching budget caps across providers',
        'Keeping system + pins anchored in context',
      ]
    : [
        'Routing primary traffic via OpenRouter /auto',
        'Watching budget caps across providers',
        'Keeping system + pins anchored in context',
        'Trimming older turns to keep tokens under control',
        'Preparing for summarization of long histories',
      ]

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_#201040_0,_#020212_60%)] text-slate-100">
      <div className="flex min-h-screen flex-col">
        <TopBar providerSnapshot={providerSnapshot} />
        <div className="flex flex-1 overflow-hidden">
          <ArdenColumn status="FOCUSED" activity={ardenActivity} />
          <div className="flex min-w-0 flex-1 flex-col">
            <RouterCore health={health} latestRoute={latestRoute} />
            <div className="px-4 pb-3">
              <ContextBudgetController
                config={budgetConfig}
                onChange={setBudgetConfig}
                contextTokens={contextTokens}
              />
            </div>
          </div>
          <BudgetPanel providers={health?.providers ?? null} />
        </div>
        <ActivityStream entries={activity} />
      </div>
    </div>
  )
}

export default App

