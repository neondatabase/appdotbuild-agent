import { defineConfig, devices } from '@playwright/test';

// calculate test timeout based on number of apps, concurrency, and wait time
const waitTime = parseInt(process.env.WAIT_TIME || '60000');
const numApps = parseInt(process.env.NUM_APPS || '1');
const concurrency = parseInt(process.env.CONCURRENCY || '3');

// worst case: (numApps / concurrency) batches * waitTime per batch + 60s overhead
const testTimeout = Math.ceil((numApps / concurrency) * waitTime) + 60000;

export default defineConfig({
  testDir: '.',
  testMatch: 'batch-screenshot.spec.ts',
  timeout: testTimeout,
  use: {
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
