// Engine tests for the shim: run with `claude plugin test plugins/token-saver`.
import { expect, test } from 'claude-code/testing'

const ROW = (id: string) =>
  ({
    plugin: 'token-saver',
    component: 'ToolUse',
    requestId: id,
    props: { tool_use_id: id, tool: 'Read', input: { file_path: '/x/notes.srt' }, isRunning: false, isErrored: false, isInterrupted: false },
  }) as const

const SAMPLE = {
  mod: 'input_router',
  title: 'input router',
  lines: ['haiku digested notes.srt', '18,400 -> 950 tokens   (-95%, est.)'],
  detail: 'DIGEST BODY',
  path: '/x/notes.srt',
}

test('a card draws under the tool row and expands, on terminal and desktop', async ($, on) => {
  // Seed the card as if the tool.call hook had stored it; other keys go to the kit.
  on('state.get', (_, e, next) =>
    e.key === 'card' && e.id === 't1' ? { value: { value: SAMPLE, version: 1 } } : next(e),
  )
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...ROW('t1'), surface })
    expect((await ui.find({ type: 'Text', text: /18,400 -> 950/ }))?.text).toContain('18,400')
    expect(await ui.find({ type: 'Text', text: /DIGEST BODY/ })).toBeUndefined()
    await ui.press({ key: 'show-t1' })
    expect((await ui.find({ type: 'Text', text: /DIGEST BODY/ }))?.text).toBe('DIGEST BODY')
    await ui.press({ key: 'show-t1' }) // collapse again for the next surface
    expect(await ui.find({ type: 'Button', key: 'full-t1' })).toBeDefined()
    await ui.unmount()
  }
})

test('no card: the row is left to the engine, nothing added', async $ => {
  const ui = await $.ui.mount({ ...ROW('t2'), surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /token-saver/ })).toBeUndefined()
  await ui.unmount()
})

test('/mods answers display-only even when Python is unreachable', async $ => {
  const r = await $.command.run({ command: 'mods', args: '' })
  expect(r.isTextDisplayOnly).toBe(true)
  expect(r.text).toContain('token-saver')
})

test('/handoff writes the doc through a fork and saves it via Python', async ($, on) => {
  const calls: string[][] = []
  let savedStdin = ''
  on('process.run', (_, e) => {
    calls.push([...e.argv])
    const cmd = e.argv[2]
    if (cmd === 'handoff-prompt') return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, text: 'WRITE HANDOFF' }), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    if (cmd === 'handoff-save') {
      savedStdin = e.init?.stdin ?? ''
      return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, text: 'Handoff saved: /x/LATEST.md' }), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    return { value: { exitCode: 0, stdout: '{"ok":true}', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  let forkPrompt = ''
  on('model.fork', (_, e) => {
    forkPrompt = e.prompt
    return { value: { isAnswered: true, text: '# Handoff\n## Goal\nX', usage: { input_tokens: 5, output_tokens: 900, cache_read_input_tokens: 250000, cache_creation_input_tokens: 0 } } }
  })
  on('session.id', () => ({ value: 'sess-1' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 252000, window: 1000000 }, rateLimits: [] } }))

  const r = await $.command.run({ command: 'handoff', args: '' })
  expect(forkPrompt).toBe('WRITE HANDOFF')
  expect(savedStdin).toBe('# Handoff\n## Goal\nX')
  const save = calls.find(c => c[2] === 'handoff-save') ?? []
  expect(save[4]).toBe('252000')
  expect(r.isTextDisplayOnly).toBe(true)
  expect(r.text).toContain('Handoff saved')
})

test('/handoff with nothing to fork says so and saves nothing', async ($, on) => {
  const calls: string[] = []
  on('process.run', (_, e) => {
    calls.push(e.argv[2] ?? '')
    return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, text: 'P' }), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('model.fork', () => ({ value: { isAnswered: false, reason: 'nothing-to-fork', usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }))
  on('session.id', () => ({ value: 'sess-2' }))
  const r = await $.command.run({ command: 'handoff', args: '' })
  expect(r.text).toContain('nothing to hand off')
  expect(calls.includes('handoff-save')).toBe(false)
})

test('/handoff <notes> passes the notes to the prompt and the save', async ($, on) => {
  const calls: string[][] = []
  on('process.run', (_, e) => {
    calls.push([...e.argv])
    return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, text: 'P' }), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('model.fork', () => ({ value: { isAnswered: true, text: '# Handoff', usage: { input_tokens: 0, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }))
  on('session.id', () => ({ value: 's' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 1, window: 1 }, rateLimits: [] } }))
  await $.command.run({ command: 'handoff', args: 'deadline Friday' })
  expect(calls.find(c => c[2] === 'handoff-prompt')?.[4]).toBe('deadline Friday')
  expect(calls.find(c => c[2] === 'handoff-save')?.[6]).toBe('deadline Friday')
})

// ---------------------------------------------------------------- cache clock
import { clockLine } from '../hooks/shim'

test('clock line: full TTL, yellow at <= 10 min, then cold (faked timestamps)', () => {
  const now = 1_800_000_000_000
  const c = (minsLeft: number) => ({ expires_at: now / 1000 + minsLeft * 60, ttl_minutes: 60, context_tokens: 84_312 })
  expect(clockLine(c(60), now)).toBe('● cache 60m · ctx 84k')
  expect(clockLine(c(47), now)).toBe('● cache 47m · ctx 84k')
  expect(clockLine(c(10), now)).toBe('◐ cache 10m · ctx 84k')
  expect(clockLine(c(4), now)).toBe('◐ cache 4m · ctx 84k')
  expect(clockLine(c(0.2), now)).toBe('◐ cache 1m · ctx 84k')
  expect(clockLine(c(-1), now)).toBe('○ cold · ctx 84k')
  expect(clockLine({ expires_at: now / 1000 + 600.5 }, now)).toBe('● cache 11m')
  expect(clockLine(undefined, now)).toBeUndefined()
})

test('session start pins the clock line from the clock file; mod off clears it', async ($, on) => {
  const statuses: (string | undefined)[] = []
  let enabled = true
  const now = 1_800_000_000_000
  on('ui.status', (_, e) => { statuses.push(e.text); return { value: undefined } })
  on('session.id', () => ({ value: 'sess-c' }))
  on('clock.now', () => ({ value: now }))
  on('fs.read', (_, e) => {
    if (e.path.endsWith('/config.json')) return { value: JSON.stringify({ cache_clock: { enabled } }) }
    if (e.path.endsWith('/cache/clock-sess-c.json')) return { value: JSON.stringify({ expires_at: now / 1000 + 4 * 60, context_tokens: 120_000 }) }
    throw new Error('ENOENT')
  })
  on('process.run', () => ({ value: { exitCode: 0, stdout: '{"ok":true}', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('env.get', (_, e) => ({ value: e.name === 'HOME' ? '/home/u' : undefined }))
  on('clock.every', () => ({ value: undefined })) // no periods in the test: the first refresh is immediate
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(statuses[statuses.length - 1]).toBe('◐ cache 4m · ctx 120k')
  enabled = false
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(statuses[statuses.length - 1]).toBeUndefined()
})

// ---------------------------------------------------------------- effort optimizer
const PROC = (stdout: unknown) => ({ value: { exitCode: 0, stdout: JSON.stringify(stdout), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
const STEP = { turnId: 't1', index: 0, model: 'claude-opus-5-5', effort: 'high' as const, messageCount: 3 }

async function drain(s: AsyncIterable<unknown>) {
  for await (const _ of s) { /* read to the end */ }
}

function effortKit(on: any, mode: 'suggest' | 'auto', answer: unknown) {
  const toasts: string[] = []
  const sent: unknown[] = []
  let toasted: () => void = () => {}
  const toastSeen = new Promise<void>(r => { toasted = r })
  on('env.get', (_: unknown, e: { name: string }) => ({ value: e.name === 'HOME' ? '/home/u' : undefined }))
  on('session.id', () => ({ value: 'sess-e' }))
  on('fs.read', (_: unknown, e: { path: string }) => {
    if (e.path.endsWith('/config.json')) return { value: JSON.stringify({ effort_optimizer: { enabled: true, mode } }) }
    throw new Error('ENOENT')
  })
  on('process.run', (_: unknown, e: { argv: string[] }) =>
    e.argv[2] === 'effort-check'
      ? PROC({ ok: true, action: 'classified', classification: { recommended: 'low', confidence: 0.8, reason: '"rename"' } })
      : e.argv[2] === 'effort-decide' ? PROC(answer) : PROC({ ok: true }))
  on('ui.toast', (_: unknown, e: { text: string }) => { toasts.push(e.text); toasted(); return { value: undefined } })
  on('prompt.submit', (_: unknown, e: { text: string }) => ({ text: e.text }))
  on('turn.step', async function* (_: unknown, e: { effort?: string; turnId: string; index: number }) {
    sent.push(e.effort)
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [] }
  })
  return { toasts, sent, toastSeen }
}

test('effort: suggest mode shows a toast and never changes or delays the request', async ($, on) => {
  const k = effortKit(on, 'suggest', { ok: true, action: 'done', text: 'token-saver: effort is high; this looks like a low task ("rename"). Run /effort low to switch.' })
  await $.prompt.submit({ text: 'rename this variable to userId' })
  await drain($.turn.step(STEP))
  expect(k.sent).toEqual(['high'])
  await k.toastSeen
  expect(k.toasts[0]).toContain('Run /effort low')
})

test('effort: auto mode applies the chosen level to the request', async ($, on) => {
  const k = effortKit(on, 'auto', { ok: true, action: 'done', apply: 'low', text: 'token-saver: effort high -> low for this prompt ("rename").' })
  await $.prompt.submit({ text: 'rename this variable to userId' })
  await drain($.turn.step(STEP))
  await drain($.turn.step({ ...STEP, index: 1 }))
  expect(k.sent).toEqual(['low', 'low'])
})

test('effort: a sub-agent request is never touched', async ($, on) => {
  const k = effortKit(on, 'auto', { ok: true, action: 'done', apply: 'low' })
  await $.prompt.submit({ text: 'rename this variable to userId' })
  await drain($.turn.step({ ...STEP, agentId: 'a1' }))
  expect(k.sent).toEqual(['high'])
})

// ---------------------------------------------------------------- keep warm
function kwKit(on: any, keepWarm: boolean, minsLeft: number, due: boolean) {
  const now = 1_800_000_000_000
  const calls: string[] = []
  let forks = 0
  on('ui.status', () => ({ value: undefined }))
  on('session.id', () => ({ value: 'sess-k' }))
  on('session.start', (_: unknown, e: { cwd: string }) => ({ cwd: e.cwd }))
  on('env.get', (_: unknown, e: { name: string }) => ({ value: e.name === 'HOME' ? '/home/u' : undefined }))
  on('clock.every', () => ({ value: undefined }))
  on('clock.now', () => ({ value: now }))
  on('fs.read', (_: unknown, e: { path: string }) => {
    if (e.path.endsWith('/config.json')) return { value: JSON.stringify({ cache_clock: { enabled: true } }) }
    if (e.path.endsWith('/cache/clock-sess-k.json')) return { value: JSON.stringify({ expires_at: now / 1000 + minsLeft * 60, keep_warm: keepWarm }) }
    throw new Error('ENOENT')
  })
  on('process.run', (_: unknown, e: { argv: string[] }) => {
    calls.push(e.argv[2] ?? '')
    return PROC(e.argv[2] === 'keepwarm-due' ? { ok: true, due } : { ok: true, text: 'logged' })
  })
  on('model.fork', () => {
    forks++
    return { value: { isAnswered: true, text: 'ok', usage: { input_tokens: 3, output_tokens: 1, cache_read_input_tokens: 40000, cache_creation_input_tokens: 0 } } }
  })
  return { calls, forks: () => forks }
}

test('keep warm: near expiry and due -> one fork ping, logged', async ($, on) => {
  const k = kwKit(on, true, 4, true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(k.forks()).toBe(1)
  expect(k.calls).toContain('keepwarm-log')
})

test('keep warm: off, or far from expiry -> no Python call, no ping', async ($, on) => {
  const k = kwKit(on, false, 4, true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const k2calls = k.calls.filter(c => c.startsWith('keepwarm'))
  expect(k2calls).toEqual([])
  expect(k.forks()).toBe(0)
})

test('keep warm: Python says not due -> no ping', async ($, on) => {
  const k = kwKit(on, true, 4, false)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(k.calls).toContain('keepwarm-due')
  expect(k.forks()).toBe(0)
})
