// AI-ASSISTED: reads the token values of each theme out of tokens.css, the one source of every value.
import css from './tokens.css?raw'

export type Tokens = Record<string, string>

/** The declarations of the first `:root { ... }` block at or after `from`. */
function rootBlock(from: number): Tokens {
  const start = css.indexOf(':root {', from)
  const body = css.slice(start, css.indexOf('}', start))
  return Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2]]))
}

/** The light theme, on `:root`. */
export const light = rootBlock(0)
/** Only the tokens that the `prefers-color-scheme: dark` block redefines. */
export const dark = rootBlock(css.indexOf('@media (prefers-color-scheme: dark)'))
/** Every token of each theme: the dark theme is the light one with the dark block's values on top. */
export const themes: Record<'light' | 'dark', Tokens> = { light, dark: { ...light, ...dark } }
