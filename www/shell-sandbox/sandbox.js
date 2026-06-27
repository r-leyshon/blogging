import { Terminal } from "https://esm.sh/@xterm/xterm@5.5.0";
import { FitAddon } from "https://esm.sh/@xterm/addon-fit@0.10.0";
import { Bash } from "https://esm.sh/just-bash@3.0.1/browser";

const HOME = "/home/user";
const DEFAULT_ENV = {
  HOME,
  USER: "sandbox",
  SHELL: "/bin/bash",
  TERM: "xterm-256color",
};

let exerciseCatalog = null;
let bash = null;
let term = null;
let fitAddon = null;
let sessionCwd = HOME;
let previousCwd = HOME;
let inputBuffer = "";
let history = [];
let historyIndex = -1;
let activeExerciseId = null;
let onDataHandler = null;
let sessionEnv = {};

function showError(message) {
  const el = document.getElementById("terminal");
  if (!el) {
    return;
  }
  el.innerHTML = "";
  const pre = document.createElement("pre");
  pre.style.color = "#f8d7da";
  pre.style.padding = "1rem";
  pre.style.margin = "0";
  pre.style.whiteSpace = "pre-wrap";
  pre.textContent = `Sandbox failed to start:\n\n${message}`;
  el.appendChild(pre);
}

function normalizeStdout(stdout) {
  return (stdout || "").trim();
}

function postToParent(message) {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ source: "shell-sandbox", ...message }, "*");
  }
}

function getExerciseById(exerciseId) {
  if (!exerciseCatalog) {
    return null;
  }
  return exerciseCatalog.exercises.find((item) => item.id === exerciseId) || null;
}

function buildInitialFiles(exercise) {
  const files = { ...(exerciseCatalog?.defaultSetup || {}) };
  if (exercise?.setup) {
    Object.assign(files, exercise.setup);
  }
  return files;
}

function getExecEnv() {
  return { ...DEFAULT_ENV, ...sessionEnv };
}

function createBashInstance(files) {
  return new Bash({
    files,
    cwd: HOME,
    env: getExecEnv(),
  });
}

function parseExportValue(raw) {
  const trimmed = raw.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function applyExportLine(line) {
  const trimmed = line.trim();
  if (!trimmed.startsWith("export ")) {
    return false;
  }

  const assignment = trimmed.slice(7).trim();
  const match = assignment.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
  if (!match) {
    return false;
  }

  sessionEnv[match[1]] = parseExportValue(match[2]);
  return true;
}

async function evaluateCheck(check) {
  const result = await bash.exec(check.run, { cwd: HOME, env: getExecEnv() });
  const stdout = normalizeStdout(result.stdout);
  const stderr = normalizeStdout(result.stderr);
  const failures = [];

  if (check.expectExit !== undefined && result.exitCode !== check.expectExit) {
    failures.push(`expected exit code ${check.expectExit}, got ${result.exitCode}`);
  }

  if (check.expectStdout !== undefined && stdout !== check.expectStdout) {
    failures.push(`expected output "${check.expectStdout}", got "${stdout || "(empty)"}"`);
  }

  if (check.expectStdoutMin !== undefined) {
    const count = Number.parseInt(stdout, 10);
    if (Number.isNaN(count) || count < check.expectStdoutMin) {
      failures.push(`expected at least ${check.expectStdoutMin}, got "${stdout || "(empty)"}"`);
    }
  }

  if (check.stdoutContains && !stdout.includes(check.stdoutContains)) {
    failures.push(`expected output to contain "${check.stdoutContains}"`);
  }

  if (check.stderrContains && !stderr.includes(check.stderrContains)) {
    failures.push(`expected stderr to contain "${check.stderrContains}"`);
  }

  return {
    label: check.label,
    passed: failures.length === 0,
    message: failures.length === 0 ? "Passed" : failures.join("; "),
  };
}

async function runExerciseChecks(exerciseId) {
  const exercise = getExerciseById(exerciseId);
  if (!exercise) {
    return {
      exerciseId,
      passed: false,
      results: [{ label: "Unknown exercise", passed: false, message: "Exercise not found" }],
    };
  }

  const results = [];
  for (const check of exercise.checks) {
    results.push(await evaluateCheck(check));
  }

  return {
    exerciseId,
    passed: results.every((item) => item.passed),
    results,
  };
}

function writePrompt() {
  const shortCwd = sessionCwd === HOME ? "~" : sessionCwd.replace(HOME, "~");
  term.write(`\r\n\x1b[32msandbox\x1b[0m:${shortCwd}$ `);
}

function writeGreeting(exercise) {
  term.clear();
  term.writeln("Shell sandbox (just-bash).");
  if (exercise) {
    term.writeln(`\x1b[36mChallenge:\x1b[0m ${exercise.title}`);
    term.writeln("Environment reset. Complete the task, then click Check my work.");
  } else {
    term.writeln("Try tutorial commands here. Refresh to reset.");
  }
  term.writeln("");
  writePrompt();
}

async function resolveCd(target) {
  const destination = target?.trim() || HOME;

  if (destination === "-") {
    if (!previousCwd) {
      return { ok: false, message: "cd: OLDPWD not set\n" };
    }
    const next = previousCwd;
    previousCwd = sessionCwd;
    sessionCwd = next;
    return { ok: true };
  }

  const quoted = destination.includes(" ")
    ? `'${destination.replace(/'/g, `'\\''`)}'`
    : destination;

  const result = await bash.exec(`cd ${quoted} && pwd`, { cwd: sessionCwd, env: getExecEnv() });
  if (result.exitCode !== 0) {
    return { ok: false, message: result.stderr || result.stdout };
  }

  previousCwd = sessionCwd;
  sessionCwd = result.stdout.trim();
  return { ok: true };
}

async function runCommand(line) {
  const trimmed = line.trim();
  if (!trimmed) {
    writePrompt();
    return;
  }

  if (trimmed === "clear") {
    term.clear();
    writePrompt();
    return;
  }

  const cdMatch = trimmed.match(/^cd(?:\s+(.*))?$/);
  if (cdMatch) {
    const cdResult = await resolveCd(cdMatch[1]);
    if (!cdResult.ok) {
      term.write(cdResult.message);
    }
    writePrompt();
    return;
  }

  if (applyExportLine(trimmed)) {
    writePrompt();
    return;
  }

  const result = await bash.exec(trimmed, { cwd: sessionCwd, env: getExecEnv() });
  if (result.stdout) {
    term.write(result.stdout.endsWith("\n") ? result.stdout : `${result.stdout}\n`);
  }
  if (result.stderr) {
    term.write(result.stderr.endsWith("\n") ? result.stderr : `${result.stderr}\n`);
  }
  writePrompt();
}

function submitLine() {
  const line = inputBuffer;
  inputBuffer = "";
  history.unshift(line);
  historyIndex = -1;
  term.write("\r\n");
  runCommand(line);
}

function replaceCurrentInput(nextValue) {
  while (inputBuffer.length > 0) {
    inputBuffer = inputBuffer.slice(0, -1);
    term.write("\b \b");
  }
  inputBuffer = nextValue;
  term.write(nextValue);
}

function bindTerminalInput() {
  if (onDataHandler) {
    term.off("data", onDataHandler);
  }

  onDataHandler = (data) => {
    switch (data) {
      case "\r":
        submitLine();
        break;
      case "\u007f":
        if (inputBuffer.length > 0) {
          inputBuffer = inputBuffer.slice(0, -1);
          term.write("\b \b");
        }
        break;
      case "\u001b[A":
        if (historyIndex < history.length - 1) {
          historyIndex += 1;
          replaceCurrentInput(history[historyIndex]);
        }
        break;
      case "\u001b[B":
        if (historyIndex > 0) {
          historyIndex -= 1;
          replaceCurrentInput(history[historyIndex]);
        } else if (historyIndex === 0) {
          historyIndex = -1;
          replaceCurrentInput("");
        }
        break;
      default:
        if (data >= " " || data === "\t") {
          inputBuffer += data;
          term.write(data);
        }
        break;
    }
  };

  term.onData(onDataHandler);
}

function resetSessionState() {
  sessionCwd = HOME;
  previousCwd = HOME;
  inputBuffer = "";
  history = [];
  historyIndex = -1;
  sessionEnv = {};
}

async function resetForExercise(exerciseId) {
  const exercise = getExerciseById(exerciseId);
  if (!exercise) {
    throw new Error(`Unknown exercise: ${exerciseId}`);
  }

  bash = createBashInstance(exercise);
  activeExerciseId = exerciseId;
  resetSessionState();
  writeGreeting(exercise);

  return { exerciseId, title: exercise.title };
}

async function handleParentMessage(event) {
  const data = event.data;
  if (!data || data.source !== "shell-challenges") {
    return;
  }

  if (data.type === "shell:reset") {
    try {
      const payload = await resetForExercise(data.exerciseId);
      postToParent({ type: "shell:reset-complete", ...payload });
    } catch (error) {
      postToParent({
        type: "shell:error",
        exerciseId: data.exerciseId,
        message: error instanceof Error ? error.message : String(error),
      });
    }
    return;
  }

  if (data.type === "shell:check") {
    try {
      const payload = await runExerciseChecks(data.exerciseId);
      postToParent({ type: "shell:check-result", ...payload });
    } catch (error) {
      postToParent({
        type: "shell:check-result",
        exerciseId: data.exerciseId,
        passed: false,
        results: [
          {
            label: "Checker error",
            passed: false,
            message: error instanceof Error ? error.message : String(error),
          },
        ],
      });
    }
  }
}

async function boot() {
  const response = await fetch("./exercises.json");
  if (!response.ok) {
    throw new Error(`Failed to load exercises.json (${response.status})`);
  }
  exerciseCatalog = await response.json();

  term = new Terminal({
    cursorBlink: true,
    convertEol: true,
    fontFamily: "Menlo, Monaco, Consolas, monospace",
    fontSize: 13,
    theme: {
      background: "#1e1e1e",
      foreground: "#f8f9fa",
      cursor: "#f8f9fa",
    },
  });

  fitAddon = new FitAddon();
  term.loadAddon(fitAddon);
  term.open(document.getElementById("terminal"));
  fitAddon.fit();
  bindTerminalInput();

  bash = createBashInstance(buildInitialFiles());
  writeGreeting();

  window.addEventListener("resize", () => fitAddon.fit());
  window.addEventListener("message", handleParentMessage);
  postToParent({ type: "shell:ready" });
}

try {
  boot().catch((error) => {
    showError(error instanceof Error ? error.message : String(error));
  });
} catch (error) {
  showError(error instanceof Error ? error.message : String(error));
}
