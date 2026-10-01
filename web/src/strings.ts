// AI-ASSISTED: every piece of UI copy in one module, so a translation can be added later.
export const strings = {
  appName: 'Vocab Quiz',
  join: { title: 'Join a quiz' },
  quiz: { title: (quizId: string) => `Quiz ${quizId}` },
  notFound: {
    title: 'Page not found',
    body: 'There is no page at this address.',
    home: 'Back to the start',
  },
} as const
