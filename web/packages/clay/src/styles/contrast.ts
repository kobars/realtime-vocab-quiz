// AI-ASSISTED: WCAG 2.2 contrast of two token colours, and the token pairs that the components draw, with their minimums.

/** The relative luminance of a `#RRGGBB` colour (WCAG 2.2). */
function luminance(hex: string): number {
  const [r = 0, g = 0, b = 0] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** The WCAG 2.2 contrast ratio of two `#RRGGBB` colours, from 1 to 21. */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05)
}

/** The minimum for text (WCAG 1.4.3) and for outlines and the focus ring (WCAG 1.4.11). */
export const MIN_TEXT = 4.5
export const MIN_NON_TEXT = 3

/** A foreground token drawn on a background token, and the ratio the pair must reach in every theme. */
export interface ContrastPair {
  fg: string
  bg: string
  min: number
}

const pair = (fg: string, bg: string, min: number): ContrastPair => ({ fg, bg, min })

/** Every pair a component draws. */
export const CONTRAST_PAIRS: readonly ContrastPair[] = [
  ...['--background', '--card', '--muted', '--highlight', '--warning-soft'].map((bg) => pair('--foreground', bg, MIN_TEXT)),
  pair('--card-foreground', '--card', MIN_TEXT),
  pair('--popover-foreground', '--popover', MIN_TEXT),
  ...['--background', '--card', '--muted'].map((bg) => pair('--muted-foreground', bg, MIN_TEXT)),
  pair('--secondary-foreground', '--secondary', MIN_TEXT),
  pair('--accent-foreground', '--accent', MIN_TEXT),
  pair('--primary', '--background', MIN_TEXT),
  pair('--primary', '--card', MIN_TEXT),
  pair('--primary-foreground', '--primary', MIN_TEXT),
  pair('--primary-foreground', '--primary-bright', MIN_TEXT),
  pair('--primary-foreground', '--primary-hover', MIN_TEXT),
  ...['--mint', '--cyan', '--sun', '--input'].map((bg) => pair('--night', bg, MIN_TEXT)),
  ...['success', 'destructive', 'warning'].flatMap((state) =>
    ['--background', '--card', `--${state}-soft`].map((bg) => pair(`--${state}`, bg, MIN_TEXT))),
  pair('--destructive-foreground', '--destructive', MIN_TEXT),
  pair('--input', '--background', MIN_NON_TEXT),
  pair('--input', '--card', MIN_NON_TEXT),
  pair('--ring', '--background', MIN_NON_TEXT),
  pair('--ring', '--card', MIN_NON_TEXT),
  pair('--primary', '--highlight', MIN_NON_TEXT),
]
