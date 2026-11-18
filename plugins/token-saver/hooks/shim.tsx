// token-saver shim: the only TypeScript in the plugin. It holds no decision
// logic; it does what only a mod can do and asks the Python side the rest:
//   - /mods and /savings answered with no model turn (display-only text)
//   - the info card under a tool row when a mod acted on that call
//   - Cache Clock: a pinned status line from the clock file the Stop hook writes
//   - Effort Optimizer: classify each prompt in the background (never blocks it),
//     suggest by toast; in auto mode set the level on each request of that turn
// Fail open everywhere: on any error the event passes through unchanged.
import { memberOf, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { TsCard } from '../types'

const CARD = { plugin: 'token-saver', key: 'card' } as const
const EXPANDED = { plugin: 'token-saver', key: 'expanded' } as const
const NOTE = { plugin: 'token-saver', key: 'note' } as const

// Tools a mod may act on; only these are checked for a card file.
const CARD_TOOLS = /^(Read|Agent|Task|mcp__.+)$/

type PyAnswer = { ok: boolean; text?: string; error?: string; context?: string | null }

async function py($: EngineInterface, args: string[], timeoutMs = 15000, stdin?: string): Promise<PyAnswer> {
  try {
    const r = await $.process.run(['python3', `${$.plugin.root}/lib/ts_cli.py`, ...args], { timeoutMs, stdin })
    return JSON.parse(r.stdout.trim() || '{}') as PyAnswer
  } catch (err) {
    return { ok: false, error: String(err).slice(0, 200) }
  }
}

async function stateHome($: EngineInterface): Promise<string> {
  const override = await $.env.get('TOKEN_SAVER_HOME')
  if (override) return override
  return `${(await $.env.get('HOME')) ?? ''}/.claude/token-saver`
}

async function loadCard($: EngineInterface, toolUseId: string): Promise<TsCard | undefined> {
  try {
    const raw = await $.fs.read(`${await stateHome($)}/cache/cards/${toolUseId}.json`)
    const c = JSON.parse(String(raw)) as TsCard
    if (typeof c.title !== 'string' || !Array.isArray(c.lines)) return undefined
    return { mod: String(c.mod ?? ''), title: c.title, lines: c.lines.map(String).slice(0, 4), detail: c.detail, path: c.path }
  } catch {
    return undefined // no card for this call: the usual case
  }
}

// ---------------------------------------------------------------- cache clock
// Python's Stop hook writes cache/clock-<session>.json; this only formats it.
export type ClockFile = { expires_at?: number; ttl_minutes?: number; context_tokens?: number | null; keep_warm?: boolean }

const WARN_S = 10 * 60

export function clockLine(c: ClockFile | undefined, nowMs: number): string | undefined {
  if (!c || typeof c.expires_at !== 'number') return undefined
  const left = c.expires_at - nowMs / 1000
  const ctx = typeof c.context_tokens === 'number' && c.context_tokens > 0
    ? ` · ctx ${Math.round(c.context_tokens / 1000)}k` : ''
  if (left <= 0) return `○ cold${ctx}`
  const mins = Math.max(1, Math.ceil(left / 60))
  return `${left > WARN_S ? '●' : '◐'} cache ${mins}m${ctx}`
}

async function clockEnabled($: EngineInterface, home: string): Promise<boolean> {
  try {
    const cfg = JSON.parse(String(await $.fs.read(`${home}/config.json`)))
    return cfg?.cache_clock?.enabled !== false
  } catch {
    return true // no config yet: defaults have the clock on
  }
}

let pinging = false

// One tool-less fork over the live transcript: it reads the main thread's cached
// prefix, which restarts the cache's TTL (measured 2026-11-18, see API-NOTES).
async function keepWarmPing($: EngineInterface, how: 'auto' | 'manual'): Promise<string> {
  if (pinging) return 'ping already running'
  pinging = true
  try {
    const fork = await $.model.fork({
      prompt: 'Keep-warm ping from token-saver. Do not think it over and use no tools; reply with exactly: ok',
    })
    if (!fork.isAnswered) return `ping not sent: ${fork.reason}`
    const r = await py($, ['keepwarm-log', await $.session.id(), JSON.stringify(fork.usage), how])
    return r.text ?? 'ping sent'
  } finally {
    pinging = false
  }
}

async function refreshClock($: EngineInterface): Promise<void> {
  try {
    const home = await stateHome($)
    let text: string | undefined
    if (await clockEnabled($, home)) {
      const sid = (await $.session.id()).replace(/[^A-Za-z0-9_-]/g, '').slice(0, 80)
      let c: ClockFile | undefined
      try {
        c = JSON.parse(String(await $.fs.read(`${home}/cache/clock-${sid}.json`))) as ClockFile
      } catch {
        c = undefined // no reply yet in this session
      }
      // The live context size beats the file's (the transcript can lag the Stop hook).
      try {
        const live = (await $.session.usage()).context.tokens
        if (c && typeof live === 'number' && live > 0) c = { ...c, context_tokens: live }
      } catch {
        // keep the file's figure
      }
      const now = await $.clock.now()
      text = clockLine(c, now)
      // Keep Warm: only near expiry, and only when the clock file says it is on;
      // Python decides (max pings, cold cache, mod off).
      if (c?.keep_warm && typeof c.expires_at === 'number' && c.expires_at - now / 1000 <= 360) {
        const due = (await py($, ['keepwarm-due', sid], 5000)) as PyAnswer & { due?: boolean }
        if (due.due) await keepWarmPing($, 'auto')
      }
    }
    $.ui.status(text)
  } catch {
    // fail open: a missing clock line is fine
  }
}

// ---------------------------------------------------------------- effort optimizer
type Effort = 'low' | 'medium' | 'high' | 'xhigh' | 'max'
const EFFORTS: readonly string[] = ['low', 'medium', 'high', 'xhigh', 'max']
let lastEffort: string | undefined          // the main thread's level, seen at turn.step
let effortKnown: (level: string) => void = () => {}
let effortSeen = new Promise<string>(r => { effortKnown = r })
let pending: { mode: string; job: Promise<Classified | undefined> } | undefined
let autoTarget: Effort | undefined

type Classified = Record<string, unknown> & { recommended?: string }
type EffortAnswer = PyAnswer & { action?: 'none' | 'ask' | 'classified' | 'done'; model?: string; system?: string; prompt?: string; classification?: Classified; apply?: string }

async function effortMode($: EngineInterface): Promise<string | undefined> {
  try {
    const cfg = JSON.parse(String(await $.fs.read(`${await stateHome($)}/config.json`)))
    const eo = cfg?.effort_optimizer
    return eo?.enabled === false ? undefined : String(eo?.mode ?? 'suggest')
  } catch {
    return 'suggest'
  }
}

// Step 1, as soon as the prompt is submitted: Python's heuristics, and Haiku on
// the session's own client only when Python asks for it.
export async function classifyEffort($: EngineInterface, text: string): Promise<Classified | undefined> {
  try {
    const sid = await $.session.id()
    let c = (await py($, ['effort-check', sid, lastEffort ?? ''], 10000, text)) as EffortAnswer
    if (c.action === 'ask' && c.prompt) {
      const m = await $.model.complete({ model: c.model ?? 'haiku', system: c.system, prompt: c.prompt, maxTokens: 200, timeoutMs: 15000 })
      if (!m.isAnswered) return undefined
      c = (await py($, ['effort-model', sid], 10000, m.text)) as EffortAnswer
    }
    return c.action === 'classified' ? c.classification : undefined
  } catch {
    return undefined // fail open: no suggestion
  }
}

// Step 2, once the current level is known: Python decides (threshold, dedupe,
// logging); the shim shows the line and, in auto mode, returns the level to use.
async function decideEffort($: EngineInterface, c: Classified, current: string): Promise<Effort | undefined> {
  try {
    const d = (await py($, ['effort-decide', await $.session.id(), current], 10000, JSON.stringify(c))) as EffortAnswer
    if (d.text) $.ui.toast(d.text, { timeoutMs: 12000 })
    return d.apply && EFFORTS.includes(d.apply) ? (d.apply as Effort) : undefined
  } catch {
    return undefined
  }
}

const DEMO: TsCard = {
  mod: 'demo',
  title: 'input router (demo card)',
  lines: ['haiku digested notes.srt', '18,400 -> 950 tokens   (-95%, est.)', '2.1 s   full file: ~/notes/notes.srt'],
  detail: 'Demo only: no file was digested. Real cards appear when a mod acts on a tool call.',
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    try {
      if ((await $.env.get('TOKEN_SAVER_INNER')) !== '1') {
        await $.command.register({
          name: 'mods',
          description: 'token-saver: list mods, on/off, set, pause/resume, reset, doctor',
          argumentHint: '[on|off <mod> | set <mod>.<key> <value> | pause | resume | reset | doctor]',
          immediate: true,
        })
        await $.command.register({
          name: 'savings',
          description: 'token-saver: tokens saved per mod',
          argumentHint: '[today|7d|all|session]',
          immediate: true,
        })
        await $.command.register({
          name: 'handoff',
          description: 'token-saver: write a detailed handoff doc, then /clear to continue fresh',
          argumentHint: '[load]',
        })
        await $.command.register({
          name: 'keepwarm',
          description: 'token-saver: keep the prompt cache warm while you are away (on|off|ping|status)',
          argumentHint: '[on|off|ping|status]',
        })
        await py($, ['shim-loaded', (await $.session.version()).version], 5000)
      }
    } catch {
      // fail open: commands missing is better than a broken session
    }
    try {
      if ((await $.env.get('TOKEN_SAVER_INNER')) !== '1') {
        // A hot reload stops the old copy's timer, so one timer per loaded copy.
        $.clock.every(30000, () => refreshClock($))
        await refreshClock($)
      }
    } catch {
      // fail open: no clock line
    }
    return next(e)
  })

  on('command.run', { command: 'mods' }, async ($, e) => {
    if (e.args.trim() === 'card-test') {
      // Attach a demo card under the most recent tool call, to preview the look.
      const msgs = await $.session.messages({ last: 20 })
      const uses = Array.isArray(msgs) ? msgs.flatMap(m => m.toolUses) : []
      const last = uses[uses.length - 1]
      if (!last) return { text: 'token-saver: no tool call in this session yet to attach a demo card to.', isTextDisplayOnly: true }
      await update($, { ...CARD, id: last.tool_use_id }, () => DEMO)
      return { text: `token-saver: demo card attached under the last ${last.tool} call.`, isTextDisplayOnly: true }
    }
    const r = await py($, ['mods', await $.session.id(), e.args])
    return { text: r.text ?? `token-saver: /mods failed: ${r.error ?? 'no answer'}`, isTextDisplayOnly: true }
  }).catch(() => ({ text: 'token-saver: /mods failed (see ~/.claude/token-saver/debug.log).', isTextDisplayOnly: true }))

  on('command.run', { command: 'savings' }, async ($, e) => {
    const r = await py($, ['savings', await $.session.id(), e.args])
    return { text: r.text ?? `token-saver: /savings failed: ${r.error ?? 'no answer'}`, isTextDisplayOnly: true }
  }).catch(() => ({ text: 'token-saver: /savings failed (see ~/.claude/token-saver/debug.log).', isTextDisplayOnly: true }))

  // /handoff: the session's own model writes the doc in a fork (tool-less, read
  // from the prompt cache), so the doc never enters the main conversation.
  on('command.run', { command: 'handoff' }, async ($, e) => {
    const sid = await $.session.id()
    if (e.args.trim() === 'load') {
      const r = await py($, ['handoff-load', sid])
      return { text: r.text ?? 'Could not load the handoff.', context: r.context ? [r.context] : undefined, isTextDisplayOnly: true }
    }
    // Ask for anything critical the next session must know (verbatim into the doc).
    // `/handoff <notes>` skips the question; with no one to ask (-p, SDK) it is skipped.
    let notes = e.args.trim()
    if (!notes && e.origin?.kind === 'composer') {
      try {
        const a = await $.ui.ask('Anything critical the next session must know? Type it under Other.', {
          header: 'Handoff',
          options: ['Nothing to add', 'Cancel handoff'],
        })
        if (a === 'Cancel handoff') return { text: 'Handoff cancelled. Nothing was written.', isTextDisplayOnly: true }
        if (a !== 'Nothing to add') notes = a.trim()
      } catch {
        return { text: 'Handoff cancelled. Nothing was written.', isTextDisplayOnly: true }
      }
    }
    const p = await py($, ['handoff-prompt', sid, notes])
    if (!p.ok || !p.text) return { text: p.text ?? `handoff failed: ${p.error ?? 'no prompt'}`, isTextDisplayOnly: true }
    $.ui.status('token-saver: writing handoff document...')
    let fork
    try {
      fork = await $.model.fork({ prompt: p.text })
    } finally {
      $.ui.status(undefined)
    }
    if (!fork.isAnswered) {
      const why = fork.reason === 'nothing-to-fork'
        ? 'nothing to hand off yet: this needs at least one reply from Claude since this session started or was resumed. Send a message first, then run /handoff'
        : `the model call failed (${fork.reason})`
      return { text: `Handoff not written: ${why}.`, isTextDisplayOnly: true }
    }
    const usage = await $.session.usage()
    const s = await py($, ['handoff-save', sid, String(usage.context.tokens ?? 0), JSON.stringify(fork.usage), notes], 15000, fork.text)
    return { text: s.text ?? `handoff not saved: ${s.error ?? 'no answer'}`, isTextDisplayOnly: true }
  }).catch(() => ({ text: 'Handoff failed (see ~/.claude/token-saver/debug.log). Nothing was changed.', isTextDisplayOnly: true }))

  // /keepwarm ping: one tool-less fork over the live transcript. It reads the main
  // thread's cached prefix, which is what may refresh the cache's TTL.
  on('command.run', { command: 'keepwarm' }, async ($, e) => {
    const sid = await $.session.id()
    const arg = e.args.trim()
    if (arg === 'ping') return { text: await keepWarmPing($, 'manual'), isTextDisplayOnly: true }
    const r = await py($, ['keepwarm', sid, arg])
    return { text: r.text ?? `keepwarm failed: ${r.error ?? 'no answer'}`, isTextDisplayOnly: true }
  }).catch(() => ({ text: 'keepwarm failed (see ~/.claude/token-saver/debug.log).', isTextDisplayOnly: true }))

  // Effort Optimizer: start classifying once the prompt is submitted; never wait on it here.
  on('prompt.submit', async ($, e, next) => {
    try {
      autoTarget = undefined
      pending = undefined
      if (!e.command && !e.isMeta && (await $.env.get('TOKEN_SAVER_INNER')) !== '1') {
        const mode = await effortMode($)
        if (mode) {
          const job = classifyEffort($, e.text)
          pending = { mode, job }
          if (mode !== 'auto') {
            // Suggest: decide in the background once the level is known (first request).
            void (async () => {
              const c = await job
              if (!c) return
              const cur = lastEffort ?? (await Promise.race([effortSeen, $.clock.sleep(120000).then(() => undefined)]))
              if (cur) await decideEffort($, c, cur)
            })().catch(() => undefined)
          }
        }
      }
    } catch {
      // fail open
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  // Track the main thread's effort; in auto mode, decide at the turn's first request
  // and apply the level to every request of the turn (a rewrite lasts one step).
  on('turn.step', async function* ($, e, next) {
    if (e.agentId !== undefined) return yield* next(e)
    if (typeof e.effort === 'string') {
      lastEffort = e.effort
      effortKnown(e.effort)
    }
    if (pending?.mode === 'auto' && typeof e.effort === 'string') {
      const job = pending.job
      pending = undefined
      const c = await Promise.race([job, $.clock.sleep(5000).then(() => undefined)]).catch(() => undefined)
      autoTarget = c ? await decideEffort($, c, e.effort) : undefined
    }
    if (autoTarget && typeof e.effort === 'string' && autoTarget !== e.effort) {
      return yield* next({ ...e, effort: autoTarget })
    }
    return yield* next(e)
  })

  // Keep Warm stops when its session ends (exit, /clear, resume elsewhere).
  on('session.end', async ($, e, next) => {
    try {
      await py($, ['keepwarm', e.sessionId, 'off'], 3000)
    } catch {
      // fail open
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  // After a call a mod may act on, pick up the card file its hook wrote.
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    try {
      if (CARD_TOOLS.test(String(e.tool))) {
        const card = await loadCard($, e.tool_use_id)
        if (card) await update($, { ...CARD, id: e.tool_use_id }, () => card)
      }
    } catch {
      // fail open: the tool result is returned untouched
    }
    return ran
  }).catch(($, e, next) => next(e)) // replays next's settled result; never blocks a tool

  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    const card = await read($, memberOf(CARD, e))
    if (!card) return next(e)
    const row = await next(e)
    const { Box, Text, Button } = $.ui.resolve(e)
    const isOpen = (await read($, memberOf(EXPANDED, e))) ?? false
    const note = await read($, memberOf(NOTE, e))
    const width = Math.max(30, Math.min(64, (e.viewport?.columns ?? 80) - 6))
    const id = e.requestId
    const path = card.path

    return (
      <Box flexDirection="column">
        {row}
        <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1} marginLeft={2} width={width}>
          <Text bold>token-saver <Text dimColor>· {card.title}</Text></Text>
          {card.lines.map(line => <Text dimColor>{line}</Text>)}
          {isOpen && card.detail ? <Text>{card.detail}</Text> : null}
          {note ? <Text color="yellow">{note}</Text> : null}
          <Box flexDirection="row">
            {card.detail ? (
              <Button key={`show-${id}`} label={isOpen ? 'hide digest' : 'show digest'}
                onPress={() => update($, { ...EXPANDED, id }, v => !v)} />
            ) : null}
            {path ? (
              <Button key={`full-${id}`} label="read full instead"
                onPress={async () => {
                  const r = await py($, ['bypass', await $.session.id(), path])
                  await update($, { ...NOTE, id }, () => (r.ok ? 'Next Read of this file passes through in full.' : 'Could not set bypass.'))
                }} />
            ) : null}
          </Box>
        </Box>
      </Box>
    )
  }).catch(($, e, next) => next(e))
}
