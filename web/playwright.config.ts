// AI-ASSISTED: Playwright runs the browser specs in e2e/ in Chromium against a running full stack.
import process from 'node:process'
import { defineConfig, devices } from '@playwright/test'
import { STACK_URL } from './e2e/stack'

export default defineConfig({
  testDir: 'e2e',
  globalSetup: './e2e/global-setup.ts',
  forbidOnly: Boolean(process.env.CI),
  workers: 1, // the specs share the stack's quizzes and its per-address request limits
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: STACK_URL,
    testIdAttribute: 'data-test',
    trace: 'retain-on-failure',
  },
  // Desktop Chrome is wider than the 1024 px breakpoint: the leaderboard sits beside the quiz.
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
