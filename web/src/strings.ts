// AI-ASSISTED: every piece of UI copy in one module, so a translation can be added later.
export const strings = {
  appName: 'Vocab Quiz',
  join: { title: 'Join a quiz' },
  quiz: { title: (quizId: string) => `Quiz ${quizId}` },
  leaderboard: {
    title: 'Leaderboard',
    counts: (players: number, online: number) => `${players} players · ${online} online`,
    updating: 'Updating…',
    you: '(you)',
    showAll: 'Show all players',
    close: 'Close',
    previous: 'Previous',
    next: 'Next',
    range: (from: number, to: number, total: number) => `Players ${from}–${to} of ${total}`,
    asOf: (seq: number) => `As of update ${seq}`,
    final: 'Final standings',
  },
  results: {
    finished: 'You finished!',
    provisional: 'Provisional',
    rank: (rank: number, players: number) => `Rank #${rank} of ${players}`,
    canChange: (time: string) => `Your rank can still change until the quiz ends in ${time}.`,
    points: (score: number) => `${score} points`,
    title: 'Final results',
    placed: (rank: number, players: number) => `You placed #${rank} of ${players}`,
  },
  notFound: {
    title: 'Page not found',
    body: 'There is no page at this address.',
    home: 'Back to the start',
  },
} as const
