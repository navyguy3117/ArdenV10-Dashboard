import { motion } from 'framer-motion'

interface TopBarProps {
  providerSnapshot?: Record<string, { daily_cost_estimate: number; monthly_cost_estimate: number }>
}

export const TopBar: React.FC<TopBarProps> = ({ providerSnapshot }) => {
  return (
    <motion.header
      className="glass-panel neon-border-purple relative z-20 flex items-center justify-between px-8 py-4"
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
    >
      <div className="flex items-center gap-3">
        <div className="relative h-8 w-8 rounded-xl bg-gradient-to-br from-neon-cyan to-neon-magenta shadow-[0_0_18px_rgba(79,242,242,0.9)]" />
        <div>
          <div className="text-xs tracking-[0.25em] text-slate-400 uppercase">Arden // Router Core</div>
          <div className="flex items-center gap-2 text-[11px] text-slate-300">
            <span className="inline-flex items-center gap-1">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-neon-cyan/60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-neon-cyan" />
              </span>
              ONLINE
            </span>
          </div>
        </div>
      </div>

      <div className="flex flex-col items-center gap-2">
        <div className="flex items-center rounded-full bg-white/5 px-3 py-1 text-[11px] font-medium text-slate-100 shadow-inner shadow-white/5">
          <span className="mr-2 rounded-full bg-gradient-to-r from-neon-cyan to-neon-magenta px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-bg-deep">
            Routing
          </span>
          <span className="text-slate-300">via</span>
          <span className="ml-2 bg-gradient-to-r from-neon-cyan/20 to-neon-magenta/20 px-2 py-0.5 rounded-full text-neon-cyan">
            OpenRouter /auto
          </span>
        </div>
        <div className="flex gap-1 text-[10px] uppercase tracking-[0.2em] text-slate-400">
          <span className="rounded-full border border-neon-cyan/60 bg-neon-cyan/10 px-2 py-0.5 text-neon-cyan">Chat</span>
          <span className="rounded-full border border-white/10 px-2 py-0.5">Code</span>
          <span className="rounded-full border border-white/10 px-2 py-0.5">Reasoning</span>
          <span className="rounded-full border border-white/10 px-2 py-0.5">Vision</span>
        </div>
      </div>

      <div className="flex items-center gap-3 text-[11px] text-slate-200">
        {['openrouter', 'openai', 'anthropic'].map((name) => {
          const snapshot = providerSnapshot?.[name]
          const label = name.toUpperCase()
          return (
            <div
              key={name}
              className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 shadow-sm shadow-black/40"
            >
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400/40 blur-[2px]" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-300" />
              </span>
              <span className="font-semibold tracking-[0.16em] text-[10px] uppercase text-slate-200">{label}</span>
              {snapshot && (
                <span className="text-[10px] text-slate-400">
                  ${snapshot.daily_cost_estimate.toFixed(2)} / day
                </span>
              )}
            </div>
          )
        })}
      </div>
    </motion.header>
  )
}
