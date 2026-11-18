// token-saver shim: the only TypeScript in the plugin. It holds no logic of
// its own; it does what only a mod can (zero-token commands, the pinned status
// entry, effort changes, $.model calls) and asks the Python side what to do.
// Fail open: every hook passes the event on if anything goes wrong.
import type { Register } from 'claude-code'

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    try {
      if ((await $.env.get('TOKEN_SAVER_INNER')) !== '1') {
        await $.process.run(
          ['python3', `${$.plugin.root}/lib/ts_cli.py`, 'shim-loaded', (await $.session.version()).version],
          { timeoutMs: 5000 },
        )
      }
    } catch {
      // fail open
    }
    return next(e)
  })
}
