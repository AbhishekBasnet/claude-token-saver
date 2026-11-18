// token-saver shim: the only TypeScript in the plugin. It holds no decision
// logic; it does what only a mod can do and asks the Python side the rest:
//   - /mods and /savings answered with no model turn (display-only text)
//   - the info card under a tool row when a mod acted on that call
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
        await py($, ['shim-loaded', (await $.session.version()).version], 5000)
      }
    } catch {
      // fail open: commands missing is better than a broken session
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
    const p = await py($, ['handoff-prompt', sid])
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
    const s = await py($, ['handoff-save', sid, String(usage.context.tokens ?? 0), JSON.stringify(fork.usage)], 15000, fork.text)
    return { text: s.text ?? `handoff not saved: ${s.error ?? 'no answer'}`, isTextDisplayOnly: true }
  }).catch(() => ({ text: 'Handoff failed (see ~/.claude/token-saver/debug.log). Nothing was changed.', isTextDisplayOnly: true }))

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
