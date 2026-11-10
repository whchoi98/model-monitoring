"""model_explorer.execute — real child processes on fake scripts, no provider is reached (v2.40.0, ADR-035)."""

import os
import sys

import pytest

from model_explorer import execute as ex
from model_explorer.examples import code_examples

SECRET = "sk-test-SECRET-0123456789"


def _env(**extra):
    return {"PATH": os.environ.get("PATH", ""), "HOME": "/tmp", **extra}


def test_a_script_that_prints_passes_on_the_first_attempt():
    out = ex.execute('print("Hello!")', env=_env(), timeout_s=30)
    assert (out.status, out.attempts, out.output_excerpt, out.error_message) == ("passed", 1, "Hello!\n", None)
    assert out.latency_ms is not None and out.latency_ms > 0


def test_an_exception_fails_after_one_retry_with_the_exception_line_first():
    out = ex.execute('raise KeyError("text")', env=_env(), timeout_s=30)
    assert (out.status, out.attempts) == ("failed", 2)
    head, _, tail = out.error_message.partition("\n")
    assert head == "KeyError: 'text'"
    assert "Traceback (most recent call last)" in tail and len(tail) <= ex.STDERR_TAIL_CHARS


def test_blank_output_fails_as_no_output():
    out = ex.execute('print("   ")', env=_env(), timeout_s=30)
    assert (out.status, out.error_message, out.attempts) == ("failed", ex.NO_OUTPUT, 2)


def test_a_call_past_the_cap_is_killed_and_fails_as_a_timeout():
    out = ex.execute("import time\ntime.sleep(30)", env=_env(), timeout_s=0.5)
    assert (out.status, out.error_message, out.attempts) == ("failed", "시간 초과 0.5초", 2)


def test_a_flap_that_passes_on_the_retry_passes_with_two_attempts(tmp_path):
    marker = tmp_path / "first"
    code = f"import pathlib\np = pathlib.Path({str(marker)!r})\nif not p.exists():\n    p.write_text('x')\n    raise SystemExit(3)\nprint('ok')"
    out = ex.execute(code, env=_env(), timeout_s=30)
    assert (out.status, out.attempts, out.output_excerpt) == ("passed", 2, "ok\n")


def test_the_key_placeholders_become_environment_reads_and_the_secret_never_enters_the_code():
    code = 'key = "<ABSK-...>"\nprint(len(key))'
    prepared = ex.prepare(code, _env(OPENAI_API_KEY=SECRET))
    assert prepared.source == 'import os\nkey = os.environ["OPENAI_API_KEY"]\nprint(len(key))'
    assert SECRET not in prepared.source
    out = ex.execute(code, env=_env(OPENAI_API_KEY=SECRET), timeout_s=30)
    assert (out.status, out.output_excerpt) == ("passed", f"{len(SECRET)}\n")


@pytest.mark.parametrize("literal, name", sorted(ex.PLACEHOLDERS.items()))
def test_a_missing_key_skips_the_example(literal, name):
    out = ex.execute(f"key = {literal}\nprint(key)", env=_env(), timeout_s=30)
    assert (out.status, out.attempts, out.error_message) == ("skipped", 0, f"자격 증명 미주입: {name}")


def test_an_unknown_placeholder_skips_the_example():
    out = ex.execute('key = "<SOME_NEW_KEY>"\nprint(key)', env=_env(), timeout_s=30)
    assert (out.status, out.error_message) == ("skipped", ex.UNKNOWN_PLACEHOLDER)


def test_the_child_gets_only_the_allow_listed_environment():
    env = _env(DB_PASSWORD="db-secret-value", JWT_SECRET_KEY="jwt-secret-value-0123456789",
               SEED_ADMIN_PASSWORD="admin-secret", AGENTCORE_MEMORY_ID="mem-1", PYTHONPATH="/nowhere",
               AWS_REGION="us-east-1", AWS_CONTAINER_CREDENTIALS_RELATIVE_URI="/v2/credentials/x",
               ANTHROPIC_API_KEY="anthropic-key-0123456789")
    code = "import os\nprint(','.join(sorted(os.environ)))"
    out = ex.execute(code, env=env, timeout_s=30)
    names = set(out.output_excerpt.strip().split(","))
    assert {"AWS_REGION", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "ANTHROPIC_API_KEY", "PATH", "HOME"} <= names
    assert not names & {"DB_PASSWORD", "JWT_SECRET_KEY", "SEED_ADMIN_PASSWORD", "AGENTCORE_MEMORY_ID", "PYTHONPATH"}


def test_secrets_printed_by_the_example_are_masked_in_stdout_and_stderr():
    env = _env(ANTHROPIC_API_KEY=SECRET, AWS_SESSION_TOKEN="session-token-0123456789", OPENAI_1P_API_KEY="short")
    code = ('import os, sys\nprint(os.environ["ANTHROPIC_API_KEY"], os.environ["OPENAI_1P_API_KEY"])\n'
            'sys.stderr.write(os.environ["AWS_SESSION_TOKEN"] + "\\n")\nraise SystemExit(1)')
    out = ex.execute(code, env=env, timeout_s=30)
    assert out.status == "failed"
    assert SECRET not in (out.output_excerpt or "") and "***" in out.output_excerpt
    assert "short" in out.output_excerpt  # values under 8 characters are not masked (they would mask common words)
    assert "session-token-0123456789" not in out.error_message and out.error_message.startswith("***")


@pytest.mark.parametrize("text, expected", [
    ("arn:aws:sts::123456789012:assumed-role/R/s", "arn:aws:sts::***:assumed-role/R/s"),
    ("arn:aws:bedrock:us-east-1:123456789012:inference-profile/x", "arn:aws:bedrock:us-east-1:***:inference-profile/x"),
    ("arn:aws:bedrock:us-east-1::foundation-model/x", "arn:aws:bedrock:us-east-1::foundation-model/x"),
    ("account 123456789012 is not an ARN", "account 123456789012 is not an ARN"),
])
def test_mask_hides_the_account_id_of_an_arn_only(text, expected):
    assert ex.mask(text, _env()) == expected


def test_an_arn_in_a_failure_is_stored_without_the_account_id():
    code = 'import sys\nprint("denied for arn:aws:sts::123456789012:assumed-role/R/s", file=sys.stderr)\nraise SystemExit(2)'
    out = ex.execute(code, env=_env(), timeout_s=30)
    assert out.status == "failed"
    assert "arn:aws:sts::***:assumed-role/R/s" in out.error_message
    assert "123456789012" not in out.error_message


def test_the_temporary_directory_is_removed_and_is_the_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(ex.tempfile, "tempdir", str(tmp_path))
    out = ex.execute("import os\nprint(os.getcwd())", env=_env(), timeout_s=30)
    cwd = out.output_excerpt.strip()
    assert cwd.startswith(str(tmp_path)) and os.path.basename(cwd).startswith("explorer-")
    assert not os.path.exists(cwd)


def test_every_placeholder_of_every_example_is_known():
    ids = ["global.anthropic.claude-opus-5", "anthropic:claude-sonnet-5-5", "openai:us-east-1:openai.gpt-6-sol",
           "openai:1p:gpt-5.5", "us.amazon.nova-2-lite-v1:0"]
    env = _env(**{name: "x" * 12 for name in ex.PLACEHOLDERS.values()})
    for model_id in ids:
        for example in code_examples(model_id):
            assert ex.prepare(example["code"]["en"], env).source is not None, (model_id, example["api_id"])


def test_the_default_python_is_the_current_interpreter():
    assert ex.execute.__kwdefaults__["python"] == sys.executable
