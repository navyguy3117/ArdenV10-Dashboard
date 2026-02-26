interface ContextBudgetConfig {
  priority: 'low' | 'normal' | 'high'
  summarizationEnabled: boolean
}

interface ContextTokensInfo {
  before: number | null
  after: number | null
}

interface ContextBudgetControllerProps {
  config: ContextBudgetConfig
  onChange: (cfg: ContextBudgetConfig) => void
  contextTokens?: ContextTokensInfo
}

export const ContextBudgetController: React.FC<ContextBudgetControllerProps> = ({ config, onChange, contextTokens }) => {
  return (
    <section className="mt-3 rounded-xl border border-white/10 bg-bg-deep/80 p-3 text-[11px] text-slate-200 shadow-inner shadow-black/40">
      <div className="flex items-center justify-between">
        <span className="uppercase tracking-[0.18em] text-slate-400">Context budget controller</span>
        <span className="text-[10px] text-slate-500">(OpenClaw token hygiene)</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-slate-400">Priority presets</span>
          <div className="flex gap-1.5">
            {(['low', 'normal', 'high'] as const).map((level) => (
              <button
                key={level}
                type="button"
                className={`rounded-full border px-3 py-1 text-[10px] capitalize ${
                  config.priority === level
                    ? 'border-neon-cyan/70 bg-neon-cyan/10 text-neon-cyan'
                    : 'border-white/10 bg-white/5 text-slate-300 hover:border-neon-cyan/40 hover:text-neon-cyan'
                }`}
                onClick={() => onChange({ ...config, priority: level })}
              >
                {level}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-slate-400">Summarization</span>
          <label className="inline-flex cursor-pointer items-center gap-2 text-[10px]">
            <span
              className={`inline-flex h-4 w-8 items-center rounded-full border border-white/10 bg-white/5 px-[2px] ${
                config.summarizationEnabled ? 'justify-end bg-neon-cyan/20 border-neon-cyan/70' : 'justify-start'
              }`}
            >
              <span className={`h-3 w-3 rounded-full bg-white shadow-[0_0_8px_rgba(255,255,255,0.8)]`} />
            </span>
            <span className="text-slate-300">
              {config.summarizationEnabled ? 'Enabled (older turns compressed)' : 'Disabled (structure only)'}
            </span>
          </label>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 text-[10px] text-slate-300">
        <div className="space-y-1">
          <div className="text-slate-400">Estimated input tokens</div>
          <div className="rounded-lg border border-white/10 bg-white/5 p-2">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Before trimming</span>
              <span className="font-mono">
                {contextTokens?.before != null ? `~${contextTokens.before}` : '~6,000'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">After trimming</span>
              <span className="font-mono text-neon-cyan">
                {contextTokens?.after != null ? `~${contextTokens.after}` : '~3,200'}
              </span>
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="text-slate-400">Strategy</div>
          <ul className="space-y-0.5 text-[10px] text-slate-300">
            <li>• Always keep system + pins</li>
            <li>• Drop oldest non-pinned first</li>
            <li>• Summarize older context into 350–500 tokens</li>
            <li>• Store summaries in router-summaries/</li>
          </ul>
        </div>
      </div>
    </section>
  )
}
