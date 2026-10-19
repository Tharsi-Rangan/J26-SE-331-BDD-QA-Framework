import { defineConfig } from 'vitest/config';

export default defineConfig({
  // Some tests run real Jest in a child process (C3-10/11). The first Jest start can take ~30 s on Windows
  // (antivirus scans new files), so the limits are 2 minutes instead of Vitest's 5 s default.
  test: { include: ['test/**/*.test.ts'], testTimeout: 120_000, hookTimeout: 120_000 },
});
