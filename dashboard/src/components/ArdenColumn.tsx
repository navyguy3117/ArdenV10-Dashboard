import { motion, useReducedMotion } from 'framer-motion'

interface ArdenColumnProps {
  status: 'IDLE' | 'FOCUSED' | 'ROUTING_HEAVY' | 'ERROR'
  activity: string[]
}

const statusColors: Record<ArdenColumnProps['status'], string> = {
  IDLE: 'from-sky-500/40 to-purple-500/40',
  FOCUSED: 'from-neon-cyan/60 to-neon-magenta/60',
  ROUTING_HEAVY: 'from-neon-orange/60 to-neon-magenta/70',
  ERROR: 'from-red-500/60 to-neon-orange/70',
}

const statusLabel: Record<ArdenColumnProps['status'], string> = {
  IDLE: 'Idle, listening',
  FOCUSED: 'Focused on routing',
  ROUTING_HEAVY: 'Handling heavy load',
  ERROR: 'Investigating errors',
}

export const ArdenColumn: React.FC<ArdenColumnProps> = ({ status, activity }) => {
  const prefersReducedMotion = useReducedMotion()

  const avatarMotion = prefersReducedMotion
    ? { scale: 1 }
    : {
        scale: [1, 1.02, 1],
      }

  const avatarTransition = prefersReducedMotion
    ? { duration: 0 }
    : {
        duration: 6,
        repeat: Infinity,
        repeatType: 'mirror' as const,
      }

  return (
    <aside className="glass-panel neon-border-cyan relative flex w-72 flex-col">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(79,242,242,0.18),transparent_55%),radial-gradient(circle_at_bottom,_rgba(255,75,225,0.12),transparent_55%)] opacity-70" />
      <div className="relative z-10 flex flex-col gap-4 p-4">
        <motion.div
          className="relative mx-auto mt-1 h-40 w-40 rounded-[1.75rem] border border-white/10 bg-black/40 p-[2px] shadow-[0_0_40px_rgba(79,242,242,0.6)]"
          animate={avatarMotion}
          transition={avatarTransition}
        >
          <div className="relative h-full w-full overflow-hidden rounded-[1.6rem] bg-gradient-to-br from-bg-nav via-purple-900/40 to-bg-nav">
            {/* Neon halo */}
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_10%,rgba(79,242,242,0.7),transparent_55%),radial-gradient(circle_at_80%_80%,rgba(255,75,225,0.4),transparent_55%)] opacity-60" />

            {/* Arden silhouette placeholder */}
            <div className="relative flex h-full flex-col items-center justify-end pb-4">
              <div className="h-20 w-20 rounded-full bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 shadow-[0_0_25px_rgba(0,0,0,0.9)]" />
              <div className="mt-[-2.25rem] h-16 w-24 rounded-[1.5rem] bg-gradient-to-br from-slate-900 to-slate-800 shadow-[0_0_26px_rgba(79,242,242,0.6)]" />

              {/* Hoodie / techwear accents */}
              <div className="absolute bottom-6 h-10 w-28 rounded-[1.5rem] border border-neon-cyan/40 bg-gradient-to-r from-neon-cyan/10 via-slate-900/80 to-neon-magenta/10" />

              {/* Eyes / glasses strip */}
              <motion.div
                className="absolute top-10 h-4 w-16 rounded-full bg-gradient-to-r from-neon-cyan/80 via-slate-200/90 to-neon-magenta/80 shadow-[0_0_20px_rgba(79,242,242,0.9)]"
                animate={prefersReducedMotion ? { opacity: 0.9 } : { opacity: [0.8, 1, 0.8] }}
                transition={prefersReducedMotion ? { duration: 0 } : { duration: 3.5, repeat: Infinity }}
              />

              {/* Floating HUD bits */}
              <div className="absolute -left-3 top-6 h-10 w-10 rounded-xl border border-neon-cyan/40 bg-bg-deep/70" />
              <div className="absolute -right-4 top-14 h-8 w-8 rounded-xl border border-neon-magenta/40 bg-bg-deep/70" />
            </div>
          </div>
        </motion.div>

        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2 text-xs uppercase tracking-[0.18em]">
            <span className="text-slate-400">Arden Operator</span>
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-slate-300">AuDHD MODE</span>
          </div>
          <div
            className={`flex items-center justify-between rounded-xl border border-white/10 bg-gradient-to-r ${statusColors[status]} px-3 py-2 text-[11px] text-slate-100 shadow-[0_0_22px_rgba(79,242,242,0.45)]`}
          >
            <div className="flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5">
                <span className="absolute inline-flex h-full w-full rounded-full bg-white/40 blur-[2px]" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-white" />
              </span>
              <span className="font-semibold tracking-[0.16em]">{status.replace('_', ' ')}</span>
            </div>
            <span className="text-[10px] text-slate-100/90">{statusLabel[status]}</span>
          </div>
        </div>

        <div className="mt-1 space-y-2 text-xs">
          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-400">What Arden is doing</div>
          <div className="space-y-2">
            {activity.slice(0, 5).map((line, idx) => (
              <motion.div
                key={idx}
                className="flex items-center gap-2 rounded-full bg-white/5 px-3 py-1.5 text-[11px] text-slate-100 shadow-inner shadow-black/40"
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.05 * idx, duration: 0.25 }}
              >
                <span className="mt-[3px] h-1 w-4 rounded-full bg-gradient-to-r from-neon-cyan to-neon-magenta" />
                <span className="leading-snug">{line}</span>
              </motion.div>
            ))}
          </div>
        </div>

        <div className="mt-3 space-y-2">
          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-400">Focus toggles</div>
          <div className="flex flex-wrap gap-2 text-[10px]">
            {['Routing', 'Budget', 'Logs'].map((label) => (
              <button
                key={label}
                type="button"
                className="rounded-full bg-white/10 px-4 py-1.5 text-slate-100 shadow-sm shadow-black/40 hover:bg-neon-cyan/20 hover:text-neon-cyan"
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </aside>
  )
}
