#!/usr/bin/env node
// Reports raw + gzipped sizes for every JS / CSS asset in `dist/`.
// Run AFTER `npm run build`. Exits non-zero if `dist/` is missing.
//
// Usage:
//   npm run build && npm run size
//
// Output format (one line per asset):
//   dist/assets/<name>  raw=<bytes>B  gz=<bytes>B  (gz=<kb> KB)

import { readdirSync, readFileSync, existsSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const dist = "dist/assets";
if (!existsSync(dist)) {
  console.error(`Missing ${dist}/. Run 'npm run build' first.`);
  process.exit(1);
}

const targets = readdirSync(dist).filter(
  (f) => f.endsWith(".js") || f.endsWith(".css"),
);
if (targets.length === 0) {
  console.error(`No .js / .css files found under ${dist}/.`);
  process.exit(1);
}

let totalRaw = 0;
let totalGz = 0;
for (const name of targets) {
  const p = join(dist, name);
  const raw = statSync(p).size;
  const gz = gzipSync(readFileSync(p)).length;
  totalRaw += raw;
  totalGz += gz;
  const kb = (gz / 1024).toFixed(2);
  console.log(`${p.padEnd(40)} raw=${raw}B  gz=${gz}B  (${kb} KB gz)`);
}
console.log("-".repeat(80));
console.log(
  `TOTAL  raw=${totalRaw}B  gz=${totalGz}B  (${(totalGz / 1024).toFixed(2)} KB gz)`,
);
