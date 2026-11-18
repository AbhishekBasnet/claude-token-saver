// token-saver's $.state contract: the info card drawn under a tool row.
export type TsCard = {
  /** which mod acted, e.g. "input_router" */
  mod: string
  /** short heading after "token-saver ·" */
  title: string
  /** 1-3 summary lines */
  lines: string[]
  /** long text revealed by "show digest" */
  detail?: string
  /** the file the card is about (enables "read full instead") */
  path?: string
}

declare module 'claude-code' {
  interface PluginState {
    'token-saver': {
      card: StateFamily<TsCard>
      expanded: StateFamily<boolean>
      note: StateFamily<string>
    }
  }
}
