#!/usr/bin/env node
// The shared installer resolves this checkout independently of the caller's cwd.
import { main } from './installer/index.mjs';

main().catch(error => {
  console.error(`\nSetup stopped: ${error.message}\nRe-run the same command to continue. Existing settings and projects are preserved.`);
  process.exitCode = 1;
});
