// AI-ASSISTED: Playwright runs the browser specs in e2e/ in Chromium: against a running full stack (on a desktop, and the phone spec on a Pixel 7), or (E2E_SUITE=ui) the visual and accessibility specs against the production build on a mocked backend.
import process from 'node:process'
import { defineConfig, devices, type PlaywrightTestConfig } from '@playwright/test'
import { STACK_URL } from './e2e/stack'

const UI_SPECS = /(visual|a11y)\.spec\.ts$/
const PHONE_SPECS = /phone\.spec\.ts$/
/** `make ui-check` runs this suite in a container, so the port is the container's own. */
const PREVIEW_URL = 'http://127.0.0.1:4173'
const WIDTHS = [320, 768, 1280]
const SCHEMES = ['light', 'dark'] as const

const stack: PlaywrightTestConfig = {
  globalSetup: './e2e/global-setup.ts',
  testIgnore: UI_SPECS,
  workers: 1, // the specs share the stack's quizzes and its per-address request limits
  use: { baseURL: STACK_URL },
  // Desktop Chrome is wider than the 1024 px breakpoint: the leaderboard sits beside the quiz. A Pixel 7 is narrower:
  // the quiz and the leaderboard are two tabs.
  projects: [
    { name: 'chromium', testIgnore: [UI_SPECS, PHONE_SPECS], use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', testMatch: PHONE_SPECS, use: { ...devices['Pixel 7'] } },
  ],
}

const ui: PlaywrightTestConfig = {
  testMatch: UI_SPECS,
  // One baseline per project for every platform: the baselines come from the pinned Playwright image only.
  snapshotPathTemplate: '{testDir}/__screenshots__/{projectName}/{arg}{ext}',
  // The pinned image renders alike on every run, so a few anti-aliased pixels are the only slack: a ratio bound such
  // as 1% would let a whole text colour change through (it touches 0.05–0.4% of a page).
  expect: { toHaveScreenshot: { maxDiffPixels: 50 } },
  webServer: {
    command: `pnpm build && pnpm exec vite preview --host 127.0.0.1 --port ${new URL(PREVIEW_URL).port} --strictPort`,
    url: PREVIEW_URL,
  },
  use: { baseURL: PREVIEW_URL },
  projects: WIDTHS.flatMap((width) =>
    SCHEMES.map((colorScheme) => ({
      name: `${width}-${colorScheme}`,
      use: { ...devices['Desktop Chrome'], viewport: { width, height: 720 }, colorScheme, reducedMotion: 'reduce' as const },
    })),
  ),
}

const suite = process.env.E2E_SUITE === 'ui' ? ui : stack

export default defineConfig({
  testDir: 'e2e',
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  ...suite,
  use: { testIdAttribute: 'data-test', trace: 'retain-on-failure', ...suite.use },
})
