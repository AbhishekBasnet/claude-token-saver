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
