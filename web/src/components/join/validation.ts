// AI-ASSISTED: the join form rules: the quiz ID pattern, the display name length after trim, and the name remembered in the tab.
import { strings } from '@/strings'

export const QUIZ_ID_PATTERN = /^[A-Z0-9-]{3,16}$/
export const QUIZ_ID_MAX = 16
export const NAME_MAX = 32
export const NAME_KEY = 'quiz.displayName'

/** The field upper-cases as the player types; anything else that breaks the pattern is reported, not removed. */
export const normalizeQuizId = (raw: string): string => raw.toUpperCase()

export const quizIdError = (quizId: string): string | null => (QUIZ_ID_PATTERN.test(quizId) ? null : strings.join.quizIdInvalid)

/** 1–32 characters after trim, counted as code points like the server does. */
export function displayNameError(name: string): string | null {
  const length = [...name.trim()].length
  if (length === 0) return strings.join.nameRequired
  return length > NAME_MAX ? strings.join.nameTooLong : null
}

/** Storage may be blocked (private mode, a sandboxed frame): the name is a convenience, so failures are ignored. */
export function readName(storage: Storage = sessionStorage): string {
  try {
    return storage.getItem(NAME_KEY) ?? ''
  } catch {
    return ''
  }
}

export function saveName(name: string, storage: Storage = sessionStorage): void {
  try {
    storage.setItem(NAME_KEY, name)
  } catch {
    // Not remembered; the join still works.
  }
}
