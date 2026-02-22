import { motion, useReducedMotion } from 'framer-motion'

interface RouterCoreProps {
  health: any | null
  latestRoute?: {
    provider: string
    model: string
    intent: string
    priority: string
  } | null
}

// Fixed orbit canvas size — provider nodes are positioned by pixel math
// to guarantee they sit inside the square without clipping.
const SIZE = 560
const CENTER = SIZE / 2   // 280
const RADIUS = 200
const NODE_SIZE = 112     // provider node px (h-28 = 7rem @ 16px = 112px)
const CORE_SIZE = 240     // core circle px

export const RouterCore: React.FC<RouterCoreProps> = ({ health, latestRoute }) => {
  const prefersReducedMotion = useReducedMotion()

  const providers = Object.entries(health?.providers ?? {}) as [
    string,
    { daily_cost_estimate: number; monthly_cost_estimate: number },
  ][]

  const activeProvider = latestRoute?.provider?.toLowerCase() ?? ''
  const displayProvider = latestRoute?.provider?.toUpperCase() ?? (health ? 'OPENROUTER' : '…')
  const displayModel = latestRoute?.model ?? (health ? 'auto' : 'connecting')

  return (
    <section className="glass-panel neon-border-purple relative flex-1 overflow-hidden">
      {/* Ambient radial tint */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_42%,_rgba(79,242,242,0.11),transparent_52%),radial-gradient(circle_at_bottom,_rgba(124,58,237,0.15),transparent_58%)]" />

      <div className="relative z-10 flex h-full flex-col">

        {/* Header row */}
        <div className="flex items-center justify-between px-5 pt-4 text-[11px]">
          <span className="uppercase tracking-[0.22em] text-slate-400">Router Core</span>
          <div className="flex items-center gap-2">
            <motion.span
              className={`h-2.5 w-2.5 rounded-full ${health ? 'bg-neon-cyan' : 'bg-slate-600'}`}
              animate={health && !prefersReducedMotion ? { opacity: [1, 0.4, 1] } : undefined}
              transition={{ duration: 2, repeat: Infinity }}
            />
            <span className={`font-mono text-[10px] tracking-widest ${health ? 'text-neon-cyan' : 'text-slate-500'}`}>
              {health ? 'ONLINE' : 'CONNECTING'}
            </span>
          </div>
        </div>

        {/* Orbit diagram — fixed 560×560 square, centred in the panel */}
        <div className="flex flex-1 items-center justify-center overflow-hidden">
          <div
            className="relative flex-shrink-0"
            style={{ width: SIZE, height: SIZE }}
          >

            {/* ── Deep background bloom ── */}
            <div
              className="pointer-events-none absolute rounded-full"
              style={{
                width: 380,
                height: 380,
                left: CENTER - 190,
                top: CENTER - 190,
                background:
                  'radial-gradient(circle, rgba(79,242,242,0.22) 0%, rgba(255,75,225,0.14) 45%, transparent 70%)',
                filter: 'blur(48px)',
              }}
            />

            {/* ── Outer orbit ring (slow clockwise) ── */}
            <motion.div
              className="router-core-ring absolute rounded-full"
              style={{ inset: 20 }}
              animate={prefersReducedMotion ? undefined : { rotate: 360 }}
              transition={
                prefersReducedMotion
                  ? undefined
                  : { duration: 60, repeat: Infinity, ease: 'linear' }
              }
            />

            {/* ── Inner orbit ring (slow counter-clockwise) ── */}
            <motion.div
              className="absolute rounded-full"
              style={{
                inset: 110,
                border: '2px solid rgba(255,75,225,0.40)',
                boxShadow: '0 0 28px rgba(255,75,225,0.40), inset 0 0 18px rgba(255,75,225,0.08)',
              }}
              animate={prefersReducedMotion ? undefined : { rotate: -360 }}
              transition={
                prefersReducedMotion
                  ? undefined
                  : { duration: 90, repeat: Infinity, ease: 'linear' }
              }
            />

            {/* ── RouterCore inner node ── */}
            <motion.div
              className="router-core-inner absolute rounded-full"
              style={{
                width: CORE_SIZE,
                height: CORE_SIZE,
                left: CENTER - CORE_SIZE / 2,
                top: CENTER - CORE_SIZE / 2,
              }}
              animate={
                prefersReducedMotion
                  ? undefined
                  : {
                      boxShadow: [
                        '0 0 55px rgba(79,242,242,0.50), 0 0 110px rgba(255,75,225,0.28)',
                        '0 0 90px rgba(79,242,242,0.78), 0 0 180px rgba(255,75,225,0.46)',
                        '0 0 55px rgba(79,242,242,0.50), 0 0 110px rgba(255,75,225,0.28)',
                      ],
                    }
              }
              transition={
                prefersReducedMotion
                  ? undefined
                  : { duration: 4, repeat: Infinity, ease: 'easeInOut' }
              }
            >
              <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
                <div className="text-[9px] uppercase tracking-[0.24em] text-slate-500">Active Route</div>

                <div className="text-xl font-black tracking-wide text-neon-cyan leading-tight drop-shadow-[0_0_12px_rgba(79,242,242,0.9)]">
                  {displayProvider}
                </div>

                <div className="rounded-full border border-neon-cyan/40 bg-neon-cyan/10 px-4 py-1 text-[11px] font-semibold text-neon-cyan">
                  {displayModel}
                </div>

                <div className="mt-1 flex flex-wrap justify-center gap-1">
                  <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[9px] text-slate-400">
                    {latestRoute?.priority ?? 'normal'}
                  </span>
                  <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[9px] text-slate-400">
                    {latestRoute?.intent ?? 'chat'}
                  </span>
                </div>
              </div>
            </motion.div>

            {/* ── Provider nodes — evenly distributed on the orbit ── */}
            {providers.map(([name], index) => {
              // Start from top (−90°) so first provider sits at 12 o'clock
              const angle =
                (index / Math.max(providers.length, 1)) * Math.PI * 2 - Math.PI / 2
              const nx = Math.cos(angle) * RADIUS
              const ny = Math.sin(angle) * RADIUS

              const isActive =
                !!activeProvider &&
                name.toLowerCase().includes(activeProvider.split('/')[0])

              return (
                <div
                  key={name}
                  className="provider-node absolute rounded-2xl"
                  style={{
                    width: NODE_SIZE,
                    height: NODE_SIZE,
                    left: CENTER + nx - NODE_SIZE / 2,
                    top: CENTER + ny - NODE_SIZE / 2,
                    ...(isActive
                      ? {
                          boxShadow:
                            '0 0 0 2px rgba(79,242,242,0.85), 0 0 32px rgba(79,242,242,0.80), 0 0 64px rgba(79,242,242,0.40)',
                        }
                      : {}),
                  }}
                >
                  <div className="flex h-full flex-col justify-between rounded-2xl bg-gradient-to-br from-bg-nav/90 via-slate-900/90 to-bg-nav/90 p-3">
                    {/* Top row: label + status dot */}
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold leading-tight tracking-[0.12em] text-slate-100">
                        {name.toUpperCase().slice(0, 12)}
                      </span>
                      <motion.span
                        className={`h-2 w-2 rounded-full ${
                          isActive
                            ? 'bg-neon-cyan shadow-[0_0_8px_rgba(79,242,242,1.0)]'
                            : 'bg-slate-600'
                        }`}
                        animate={
                          isActive && !prefersReducedMotion
                            ? { opacity: [1, 0.35, 1] }
                            : undefined
                        }
                        transition={{ duration: 1.6, repeat: Infinity }}
                      />
                    </div>

                    {/* Status + usage bar */}
                    <div className="space-y-1.5 text-[9px] text-slate-500">
                      <div className={isActive ? 'text-neon-cyan' : ''}>
                        {isActive ? '◆ ACTIVE' : '◇ READY'}
                      </div>
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                        <motion.div
                          className="h-full rounded-full bg-gradient-to-r from-neon-cyan to-neon-magenta"
                          animate={
                            isActive && !prefersReducedMotion
                              ? { width: ['55%', '85%', '55%'] }
                              : undefined
                          }
                          transition={{ duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}
                          style={{ width: isActive ? '65%' : '12%' }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </section>
  )
}
