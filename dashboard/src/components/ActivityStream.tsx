import { motion, useReducedMotion } from 'framer-motion'

export interface ActivityEntry {
  timestamp: string
  level: 'INFO' | 'WARN' | 'ERROR'
  source: string
  message: string
}

interface ActivityStreamProps {
  entries: ActivityEntry[]
}

const levelColors: Record<ActivityEntry['level'], string> = {
  INFO: 'text-neon-cyan',
  WARN: 'text-amber-300',
  ERROR: 'text-red-400',
}

export const ActivityStream: React.FC<ActivityStreamProps> = ({ entries }) => {
  const prefersReducedMotion = useReducedMotion()

  return (
    <section className="glass-panel neon-border-purple relative h-52">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_left,_rgba(79,242,242,0.16),transparent_60%),radial-gradient(circle_at_right,_rgba(255,75,225,0.16),transparent_60%)]" />
      <div className="relative z-10 flex h-full flex-col">
        <div className="flex items-center justify-between px-4 pt-2 text-[11px]">
          <div className="uppercase tracking-[0.18em] text-slate-400">Live activity stream</div>
          <div className="flex gap-1 text-[10px] text-slate-500">
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">All</span>
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">Routing</span>
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">Budget</span>
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">Errors</span>
          </div>
        </div>
        <div className="mt-1 flex-1 overflow-hidden px-2 pb-2">
          <div className="h-full overflow-y-auto rounded-xl bg-bg-deep/80 px-4 py-3 text-[12px] text-slate-200 shadow-inner shadow-black/60">
            <div className="space-y-2.5">
              {entries.map((entry, idx) => (
                <motion.div
                  key={`${entry.timestamp}-${idx}`}
                  className="flex items-start gap-2"
                  initial={prefersReducedMotion ? undefined : { opacity: 0, y: 4 }}
                  animate={prefersReducedMotion ? undefined : { opacity: 1, y: 0 }}
                  transition={{ duration: 0.18, delay: prefersReducedMotion ? 0 : idx * 0.03 }}
                >
                  <span className="mt-[2px] font-mono text-[11px] text-slate-500">{entry.timestamp}</span>
                  <span className={`mt-[2px] text-[11px] font-semibold ${levelColors[entry.level]}`}>
                    {entry.level}
                  </span>
                  <span className="mt-[2px] rounded-full bg-white/10 px-3 py-0.5 text-[10px] text-slate-200">
                    {entry.source}
                  </span>
                  <span className="flex-1 leading-snug text-slate-200">{entry.message}</span>
                </motion.div>
              ))}
            </div>
          </div>
        </div>
        <div className="pointer-events-none relative mt-1 h-1 w-full overflow-hidden">
          <motion.div
            className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-neon-cyan/60 to-transparent"
            animate={prefersReducedMotion ? undefined : { x: ['-30%', '120%'] }}
            transition={prefersReducedMotion ? undefined : { duration: 6, repeat: Infinity, ease: 'linear' }}
          />
        </div>
      </div>
    </section>
  )
}
