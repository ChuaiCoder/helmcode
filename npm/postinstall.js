"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const packageRoot = path.resolve(__dirname, "..");
const venvDir = path.join(packageRoot, ".venv");

function log(message) {
  console.log(`helmcode postinstall: ${message}`);
}

function run(command, args, options = {}) {
  return spawnSync(command, args, {
    cwd: packageRoot,
    stdio: options.stdio || "inherit",
    env: {
      ...process.env,
      PYTHONIOENCODING: process.env.PYTHONIOENCODING || "utf-8",
      PYTHONUTF8: process.env.PYTHONUTF8 || "1"
    }
  });
}

function checkPython(command, prefixArgs) {
  const result = spawnSync(
    command,
    [
      ...prefixArgs,
      "-c",
      "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    ],
    {
      cwd: packageRoot,
      stdio: "ignore"
    }
  );
  if (result.error || result.status !== 0) {
    return null;
  }
  return { command, prefixArgs };
}

function findPython() {
  if (process.env.HELMCODE_PYTHON) {
    const configured = checkPython(process.env.HELMCODE_PYTHON, []);
    if (configured) {
      return configured;
    }
  }
  for (const candidate of [
    { command: "python", prefixArgs: [] },
    { command: "python3", prefixArgs: [] },
    { command: "py", prefixArgs: ["-3"] }
  ]) {
    const found = checkPython(candidate.command, candidate.prefixArgs);
    if (found) {
      return found;
    }
  }
  return null;
}

function venvPythonPath() {
  if (process.platform === "win32") {
    return path.join(venvDir, "Scripts", "python.exe");
  }
  return path.join(venvDir, "bin", "python");
}

if (process.env.HELMCODE_SKIP_PYTHON_INSTALL === "1") {
  log("skipping Python environment setup because HELMCODE_SKIP_PYTHON_INSTALL=1");
  process.exit(0);
}

const python = findPython();
if (!python) {
  log("Python 3.11+ was not found; the helmcode command will use system Python if available later.");
  process.exit(0);
}

if (!fs.existsSync(venvDir)) {
  log("creating Python virtual environment");
  const created = run(python.command, [...python.prefixArgs, "-m", "venv", venvDir]);
  if (created.status !== 0) {
    log("could not create virtual environment; the helmcode command will fall back to system Python.");
    process.exit(0);
  }
}

const venvPython = venvPythonPath();
if (!fs.existsSync(venvPython)) {
  log("virtual environment Python was not found; skipping package installation.");
  process.exit(0);
}

log("installing Python package into the bundled virtual environment");
const installed = run(venvPython, ["-m", "pip", "install", "."], { stdio: "inherit" });
if (installed.status !== 0) {
  log("Python package installation failed; the helmcode command will fall back to system Python.");
  process.exit(0);
}

log("ready");
