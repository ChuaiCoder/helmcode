#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const packageRoot = path.resolve(__dirname, "..");
const args = process.argv.slice(2);

function venvPythonPath() {
  if (process.platform === "win32") {
    return path.join(packageRoot, ".venv", "Scripts", "python.exe");
  }
  return path.join(packageRoot, ".venv", "bin", "python");
}

function pythonCandidates() {
  const candidates = [];
  if (process.env.HELMCODE_PYTHON) {
    candidates.push({ command: process.env.HELMCODE_PYTHON, prefixArgs: [] });
  }
  const venvPython = venvPythonPath();
  if (fs.existsSync(venvPython)) {
    candidates.push({ command: venvPython, prefixArgs: [] });
  }
  candidates.push({ command: "python", prefixArgs: [] });
  candidates.push({ command: "python3", prefixArgs: [] });
  if (process.platform === "win32") {
    candidates.push({ command: "py", prefixArgs: ["-3"] });
  }
  return candidates;
}

function runCandidate(candidate) {
  const env = {
    ...process.env,
    PYTHONIOENCODING: process.env.PYTHONIOENCODING || "utf-8",
    PYTHONUTF8: process.env.PYTHONUTF8 || "1",
    PYTHONPATH: process.env.PYTHONPATH
      ? `${packageRoot}${path.delimiter}${process.env.PYTHONPATH}`
      : packageRoot
  };
  const result = spawnSync(
    candidate.command,
    [...candidate.prefixArgs, "-m", "helmcode.cli.main", ...args],
    {
      cwd: process.cwd(),
      env,
      stdio: "inherit"
    }
  );
  return result;
}

for (const candidate of pythonCandidates()) {
  const result = runCandidate(candidate);
  if (result.error && result.error.code === "ENOENT") {
    continue;
  }
  if (result.error) {
    console.error(`helmcode: failed to start Python: ${result.error.message}`);
    process.exit(1);
  }
  process.exit(result.status === null ? 1 : result.status);
}

console.error(
  "helmcode: Python 3.11+ was not found. Install Python, or set HELMCODE_PYTHON to a Python executable."
);
process.exit(1);
