// AI-ASSISTED: the protocol frames the mocked server sends, typed by the generated contract types.
import type { AnswerResult, Entry, Joined, Question, Snapshot, You } from '../../src/protocol/types.generated'

export const QUIZ_ID = 'VOCAB-42'
export const QUESTION_COUNT = 10
export const TIME_LIMIT_MS = 20_000
export const ME = { userId: 'u-ana', displayName: 'Ana' }
/** The correct choice of every question. */
export const CORRECT = 2
const PLAYERS = 250
const ONLINE = 180
/** Far below the top 50, so the leaderboard pins my row under them. */
const MY_PLACE: You = { rank: 137, score: 420 }

/** The top 50 of 250 players; every frame above 200 players carries only these. */
const TOP: Entry[] = Array.from({ length: 50 }, (_, i) => ({
  rank: i + 1,
  userId: `u-${i + 1}`,
  displayName: `Player ${String(i + 1).padStart(2, '0')}`,
  score: 1500 - i * 20,
}))

export const joined = (finished: boolean): Joined => ({
  v: 1,
  type: 'joined',
  atSeq: 7,
  quizId: QUIZ_ID,
  ...ME,
  questionCount: QUESTION_COUNT,
  timeLimitMs: TIME_LIMIT_MS,
  quizRemainingMs: 9 * 60_000 + 30_000,
  cursor: finished ? QUESTION_COUNT - 1 : -1,
  cursorOpen: false,
  finished,
  score: finished ? MY_PLACE.score : 0,
})

export const snapshot = (status: Snapshot['status']): Snapshot => ({
  v: 1,
  type: 'snapshot',
  atSeq: 7,
  status,
  playerCount: PLAYERS,
  onlineCount: ONLINE,
  entries: TOP,
  you: MY_PLACE,
})

export const question = (questionIndex: number): Question => ({
  v: 1,
  type: 'question',
  atSeq: 7,
  questionIndex,
  questionId: `q-${questionIndex}`,
  prompt: 'Which word means “very happy”?',
  choices: ['Gloomy', 'Weary', 'Elated', 'Sullen'],
  timeLimitMs: TIME_LIMIT_MS,
  remainingMs: TIME_LIMIT_MS,
})

export function answerResult(questionIndex: number, choiceIndex: number, submissionId: string): AnswerResult {
  const correct = choiceIndex === CORRECT
  const pointsAwarded = correct ? 138 : 0
  return {
    v: 1,
    type: 'answer_result',
    atSeq: 7,
    questionIndex,
    submissionId,
    choiceIndex,
    correctChoiceIndex: CORRECT,
    correct,
    late: false,
    pointsAwarded,
    score: pointsAwarded,
  }
}
