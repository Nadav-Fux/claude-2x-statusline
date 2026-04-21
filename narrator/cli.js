#!/usr/bin/env node
// Tiny CLI wrapper for the narrator-node module.
// Usage: node narrator/cli.js <session_start|prompt_submit>
// Called by the shell hooks so we avoid embedding Windows paths in node -e.

const path = require('path');
const narrator = require(path.join(__dirname, 'narrator-node.js'));

const mode = process.argv[2] || 'prompt_submit';

(async () => {
  try {
    const text = await narrator.run(mode);
    if (text) process.stdout.write(text + '\n');
  } catch {}
})();
