import { Terminal } from "https://esm.sh/@xterm/xterm@5.5.0";
import { FitAddon } from "https://esm.sh/@xterm/addon-fit@0.10.0";
import { Bash } from "https://esm.sh/just-bash@3.0.1/browser";

const HOME = "/home/user";
let sessionCwd = HOME;
let previousCwd = HOME;
let inputBuffer = "";
let history = [];
let historyIndex = -1;

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

try {
  const term = new Terminal({
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

  const fitAddon = new FitAddon();
  term.loadAddon(fitAddon);
  term.open(document.getElementById("terminal"));
  fitAddon.fit();

  const bash = new Bash({
    files: {
      "/home/user/welcome.txt":
        "Welcome. Try tutorial commands here. Refresh to reset.\n",
    },
    cwd: HOME,
    env: {
      HOME,
      USER: "sandbox",
      SHELL: "/bin/bash",
      TERM: "xterm-256color",
    },
  });

  function writePrompt() {
    const shortCwd = sessionCwd === HOME ? "~" : sessionCwd.replace(HOME, "~");
    term.write(`\r\n\x1b[32msandbox\x1b[0m:${shortCwd}$ `);
  }

  function writeGreeting() {
    term.writeln("Shell sandbox (just-bash).");
    term.writeln("Try tutorial commands here. Refresh to reset.");
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

    const result = await bash.exec(`cd ${quoted} && pwd`, { cwd: sessionCwd });
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

    const result = await bash.exec(trimmed, { cwd: sessionCwd });
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

  term.onData((data) => {
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
  });

  function replaceCurrentInput(nextValue) {
    while (inputBuffer.length > 0) {
      inputBuffer = inputBuffer.slice(0, -1);
      term.write("\b \b");
    }
    inputBuffer = nextValue;
    term.write(nextValue);
  }

  window.addEventListener("resize", () => fitAddon.fit());
  writeGreeting();
} catch (error) {
  showError(error instanceof Error ? error.message : String(error));
}
