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
