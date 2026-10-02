// AI-ASSISTED: scopes one theme's tokens to a panel, so the gallery shows light and dark side by side whatever the OS uses.
import { dark, themes } from '../src/tokens'

export type Theme = keyof typeof themes
export const THEMES = Object.keys(themes) as Theme[]

/**
 * The tokens a panel redeclares: those the dark theme changes, and those that read another token (a custom property
 * resolves its var() where it is declared, so the shadows and gradients must be declared again under the panel's
 * colours). The durations stay on :root, where reduced motion zeroes them.
 */
const SCOPED = Object.keys(themes.light).filter((name) => name in dark || themes.light[name]?.includes('var('))

export function themeStyle(theme: Theme): Record<string, string> {
  return Object.fromEntries([...SCOPED.map((name) => [name, themes[theme][name] ?? '']), ['color-scheme', theme]])
}

/** The tokens of a theme whose value is a plain colour. */
export function colourTokens(theme: Theme): [string, string][] {
  return Object.entries(themes[theme]).filter(([, value]) => /^#[0-9A-F]{6}$/i.test(value))
}

/** A ratio as the specs print it, for example 4.67:1. */
export const ratio = (value: number): string => `${value.toFixed(2)}:1`
