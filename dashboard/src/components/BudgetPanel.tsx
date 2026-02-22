interface BudgetPanelProps {
  providers: Record<string, { daily_cost_estimate: number; monthly_cost_estimate: number }> | null
}

export const BudgetPanel: React.FC<BudgetPanelProps> = ({ providers }) => {
  const entries = Object.entries(providers ?? {})

  return (
    <aside className="glass-panel neon-border-magenta relative w-80">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(255,75,225,0.14),transparent_55%),radial-gradient(circle_at_bottom,_rgba(249,115,22,0.14),transparent_60%)]" />

      <div className="relative z-10 flex h-full flex-col gap-5 p-5 text-xs text-slate-200">

        {/* Header */}
        <div className="flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-[0.22em] text-slate-400">Budget & Spend</span>
          <span className="rounded-full border border-neon-magenta/30 bg-neon-magenta/10 px-2 py-0.5 text-[9px] text-neon-magenta">
            LIVE
          </span>
        </div>

        {/* Provider cards */}
        <div className="flex flex-col gap-4">
          {entries.length === 0 && (
            <div className="flex flex-col items-center gap-3 py-6 text-center text-slate-500 text-[11px]">
              <div className="h-20 w-20 rounded-full border-4 border-slate-800 flex items-center justify-center text-slate-600 text-lg">
                –
              </div>
              <span>Waiting for router data…</span>
            </div>
          )}

          {entries.map(([provider, snapshot]) => {
            const dailyPct = Math.min(snapshot.daily_cost_estimate / 2.0, 1)
            const monthlyPct = Math.min(snapshot.monthly_cost_estimate / 60.0, 1)

            // Stroke math for 96px SVG (viewBox 0 0 40 40, r=17)
            const circumference = 2 * Math.PI * 17  // ≈ 106.8
            const dailyDash = dailyPct * circumference
            const dailyGap = circumference - dailyDash

            return (
              <div
                key={provider}
                className="rounded-2xl border border-white/5 bg-bg-deep/80 p-4 shadow-inner shadow-black/60"
              >
                {/* Provider name row */}
                <div className="mb-3 flex items-center justify-between text-[11px]">
                  <span className="font-bold tracking-[0.16em] text-slate-100">
                    {provider.toUpperCase()}
                  </span>
                  <span className="text-slate-400 tabular-nums">
                    ${snapshot.daily_cost_estimate.toFixed(3)}/day
                  </span>
                </div>

                {/* Circular meter + bar */}
                <div className="flex items-center gap-4">
                  {/* Daily ring — 96×96 */}
                  <div className="relative h-24 w-24 flex-shrink-0">
                    <svg viewBox="0 0 40 40" className="h-24 w-24 -rotate-90">
                      {/* Track */}
                      <circle
                        cx="20" cy="20" r="17"
                        fill="none"
                        stroke="rgba(30,41,59,1)"
                        strokeWidth="4"
                      />
                      {/* Arc */}
                      <circle
                        cx="20" cy="20" r="17"
                        fill="none"
                        stroke="url(#budgetGrad)"
                        strokeWidth="4"
                        strokeDasharray={`${dailyDash} ${dailyGap}`}
                        strokeLinecap="round"
                        style={{
                          filter: `drop-shadow(0 0 4px rgba(79,242,242,${0.4 + dailyPct * 0.5}))`,
                        }}
                      />
                      <defs>
                        <linearGradient id="budgetGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                          <stop offset="0%" stopColor="#4FF2F2" />
                          <stop offset="100%" stopColor="#FF4BE1" />
                        </linearGradient>
                      </defs>
                    </svg>
                    {/* Center label */}
                    <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
                      <div className="text-[9px] text-slate-500 leading-none">Daily</div>
                      <div className="text-sm font-bold text-neon-cyan leading-tight tabular-nums">
                        {Math.round(dailyPct * 100)}%
                      </div>
                    </div>
                  </div>

                  {/* Monthly bar + label */}
                  <div className="flex flex-1 flex-col gap-2">
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-slate-400">Monthly</span>
                      <span className="tabular-nums text-slate-300">
                        ${snapshot.monthly_cost_estimate.toFixed(2)}
                        <span className="text-slate-600"> / 60</span>
                      </span>
                    </div>
                    <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-900">
                      <div
                        className="h-2.5 rounded-full bg-gradient-to-r from-neon-cyan via-neon-magenta to-neon-orange transition-all duration-700"
                        style={{
                          width: `${monthlyPct * 100}%`,
                          boxShadow: `0 0 8px rgba(79,242,242,${0.3 + monthlyPct * 0.5})`,
                        }}
                      />
                    </div>
                    <div className="text-[9px] text-slate-500">
                      {Math.round(monthlyPct * 100)}% of monthly cap
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </aside>
  )
}
