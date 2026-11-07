"""Run one Model Explorer code example in a child Python (v2.40.0, ADR-035).

The example text is executed as shown, with only its key placeholders replaced by os.environ[...] expressions (the
secret values never enter the code text). Each run gets a fresh temporary directory as its cwd and runs
`<python> -I example.py`: -I drops PYTHON* variables, the user site and the script directory from sys.path. The child
environment is an allow-list (AWS_*, the four provider keys, PATH, HOME, LANG, LC_ALL, TMPDIR), so DB_*,
JWT_SECRET_KEY, SEED_ADMIN_PASSWORD and AGENTCORE_MEMORY_ID of the scheduled task never reach it. Output goes to a
public API, so every secret value of 8 characters or more is masked before it is returned.

Verdict: exit 0 with non-blank stdout = passed; exit 0 with blank stdout = failed "출력 없음" (an InvokeModel reply
that only had a thinking block lands here); any other exit = failed with the last non-blank stderr line and the
stderr tail; past the per-call cap = failed "시간 초과 N초"; a placeholder this module does not know or a provider key
that is not injected = skipped. A failed example runs once more and the second result decides (service flaps).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Mapping

# Example literal -> the environment variable it reads in the child. Every placeholder an example may contain must be
# here (tests pin it), or the example is skipped rather than run with a literal "<...>" key.
PLACEHOLDERS: dict[str, str] = {
    '"<ANTHROPIC_API_KEY>"': "ANTHROPIC_API_KEY",
    '"<ANTHROPIC_WORKSPACE_ID>"': "ANTHROPIC_WORKSPACE_ID",
    '"<ABSK-...>"': "OPENAI_API_KEY",
    '"<OPENAI_API_KEY>"': "OPENAI_1P_API_KEY",
}
SECRET_ENV: tuple[str, ...] = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "OPENAI_API_KEY", "OPENAI_1P_API_KEY",
    "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_CONTAINER_AUTHORIZATION_TOKEN",
)
_PASS_ENV: frozenset[str] = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "OPENAI_API_KEY", "OPENAI_1P_API_KEY",
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR",
})
_LEFTOVER = re.compile(r'"<[^"\n]*>"')
_MIN_SECRET_LEN = 8
EXCERPT_CHARS = 300
STDERR_TAIL_CHARS = 1500
DEFAULT_CALL_TIMEOUT_S = 90.0

UNKNOWN_PLACEHOLDER = "알 수 없는 플레이스홀더"
NO_OUTPUT = "출력 없음"


def call_timeout_s() -> float:
    """EXPLORER_CALL_TIMEOUT_S (default 90), read at call time."""
    return float(os.getenv("EXPLORER_CALL_TIMEOUT_S", str(DEFAULT_CALL_TIMEOUT_S)))


@dataclass(frozen=True)
class Prepared:
    source: str | None       # the code to run (import os + substituted text), None when skipped
    skip_reason: str | None


@dataclass(frozen=True)
class Outcome:
    status: str               # passed | failed | skipped
    latency_ms: float | None
    attempts: int             # 0 when skipped, else 1 or 2
    output_excerpt: str | None
    error_message: str | None  # failed: first line = the exception line, then the stderr tail; skipped: the reason


def prepare(code: str, env: Mapping[str, str]) -> Prepared:
    """Replace the key placeholders with os.environ[...] and check that every key the example reads is injected."""
    source = code
    needed: list[str] = []
    for literal, name in PLACEHOLDERS.items():
        if literal in source:
            source = source.replace(literal, f'os.environ["{name}"]')
            needed.append(name)
    if _LEFTOVER.search(source):
        return Prepared(None, UNKNOWN_PLACEHOLDER)
    missing = [name for name in needed if not env.get(name)]
    if missing:
        return Prepared(None, f"자격 증명 미주입: {', '.join(missing)}")
    return Prepared("import os\n" + source, None)


def child_env(env: Mapping[str, str]) -> dict[str, str]:
    """The allow-listed environment of the child: AWS_* (task role credentials included) and _PASS_ENV."""
    return {k: v for k, v in env.items() if k.startswith("AWS_") or k in _PASS_ENV}


def mask(text: str, env: Mapping[str, str]) -> str:
    for name in SECRET_ENV:
        value = env.get(name)
        if value and len(value) >= _MIN_SECRET_LEN:
            text = text.replace(value, "***")
    return text


def _last_line(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


def _run_once(source: str, env: Mapping[str, str], timeout_s: float, python: str) -> tuple[str, float, str | None, str | None]:
    """(status, latency_ms, output_excerpt, error_message) of one child run."""
    workdir = tempfile.mkdtemp(prefix="explorer-")
    try:
        path = os.path.join(workdir, "example.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
        started = time.monotonic()
        try:
            proc = subprocess.run(
                [python, "-I", path], cwd=workdir, env=child_env(env), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return "failed", (time.monotonic() - started) * 1000.0, None, f"시간 초과 {timeout_s:g}초"
        latency_ms = (time.monotonic() - started) * 1000.0
        stdout, stderr = mask(proc.stdout, env), mask(proc.stderr, env)
        if proc.returncode == 0 and stdout.strip():
            return "passed", latency_ms, stdout[:EXCERPT_CHARS], None
        if proc.returncode == 0:
            return "failed", latency_ms, None, NO_OUTPUT
        head = _last_line(stderr) or f"exit code {proc.returncode}"
        return "failed", latency_ms, stdout[:EXCERPT_CHARS] or None, f"{head}\n{stderr[-STDERR_TAIL_CHARS:]}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def execute(code: str, *, env: Mapping[str, str] | None = None, timeout_s: float | None = None,
            python: str = sys.executable) -> Outcome:
    """Run one example; a failed run is retried once and the second result decides."""
    env = dict(os.environ) if env is None else env
    timeout_s = call_timeout_s() if timeout_s is None else timeout_s
    prepared = prepare(code, env)
    if prepared.source is None:
        return Outcome("skipped", None, 0, None, prepared.skip_reason)
    status, latency_ms, excerpt, error = _run_once(prepared.source, env, timeout_s, python)
    attempts = 1
    if status == "failed":
        status, latency_ms, excerpt, error = _run_once(prepared.source, env, timeout_s, python)
        attempts = 2
    return Outcome(status, round(latency_ms, 1), attempts, excerpt, error)
