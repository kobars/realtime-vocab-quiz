// AI-ASSISTED: the join form rules: the quiz ID pattern, the display name length after trim and NFC with one visible character, and the name remembered in the tab.
import { strings } from '@/strings'

export const QUIZ_ID_PATTERN = /^[A-Z0-9-]{3,16}$/
export const QUIZ_ID_MAX = 16
export const NAME_MAX = 32
export const NAME_KEY = 'quiz.displayName'

/** The field upper-cases as the player types; anything else that breaks the pattern is reported, not removed. */
export const normalizeQuizId = (raw: string): string => raw.toUpperCase()

export const quizIdError = (quizId: string): string | null => (QUIZ_ID_PATTERN.test(quizId) ? null : strings.join.quizIdInvalid)

/**
 * A character that draws something: not a control, format or other `C` character, a separator or a combining mark, and
 * not one of the letters that draw as blank space (the Hangul fillers and the blank Braille pattern). The server's rule.
 */
const VISIBLE = /[^\p{C}\p{Z}\p{M}\u115F\u1160\u3164\uFFA0\u2800]/u

/**
 * 1–32 characters after trim and NFC normalization, counted as code points like the server does, at least one of them
 * visible. Invisible characters inside a visible name stay: a zero-width joiner holds an emoji sequence together.
 */
export function displayNameError(name: string): string | null {
  const normalized = name.trim().normalize('NFC')
  const length = [...normalized].length
  if (length === 0) return strings.join.nameRequired
  if (length > NAME_MAX) return strings.join.nameTooLong
  return VISIBLE.test(normalized) ? null : strings.join.nameInvisible
}

/**
 * Storage may be blocked (private mode, a sandboxed frame), and then even reading `sessionStorage` throws: the name is
 * a convenience, so failures are ignored.
 */
export function readName(storage?: Storage): string {
  try {
    return (storage ?? sessionStorage).getItem(NAME_KEY) ?? ''
  } catch {
    return ''
  }
}

export function saveName(name: string, storage?: Storage): void {
  try {
    ;(storage ?? sessionStorage).setItem(NAME_KEY, name)
  } catch {
    // Not remembered; the join still works.
  }
}
