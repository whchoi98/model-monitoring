"""인사이트 요약의 Bedrock 호출 — 60초 read timeout 실패 수정(v2.32.2, 2026-09-30).

운영: EN 요약이 24시간 279건 중 109건 `EN insight generation failed; KO만 저장`(botocore ReadTimeoutError, read timeout=60)
으로 빠졌다. 비스트림 converse는 생성이 끝나야 첫 바이트가 오는데, Sonnet 4.6이 출력 약 6.3k토큰(EN p50)을 초당 90~110토큰으로
만드는 데 55~75초가 걸린다(호출 로그 48시간: EN 85%, KO 37%가 60초 초과). 기본 client는 legacy 재시도(5회)라 실패 한 번이
5 × 60초 + backoff이고, 태스크가 6~7분으로 늘어 5분 주기의 다음 태스크와 겹쳤다. 서버는 포기한 시도도 끝까지 생성해
과금했다(버려진 시도 72%).

바뀐 것(insights_runner, agent/bedrock.py):
- 인사이트 전용 client(agent.bedrock.insights_client): connect 10초, read 60초, botocore standard 재시도 total_max_attempts 2.
  챗봇, follow-up, stream-regenerate의 _client()는 그대로다.
- converse_stream으로 받는다(converse_stream_collect). read timeout은 청크 사이 대기 상한이 되고, 호출 전체는
  stream_watchdog.CallWatchdog의 wall-clock 상한(INSIGHTS_CALL_WALL_CLOCK_S, 기본 180초)으로 끊는다. botocore 재시도는 스트림이
  열리기 전(헤더 대기)에만 일어나 생성을 다시 과금하지 않는다.
- KO와 EN을 동시에 만든다(워커 2개). KO가 실패하면 저장하지 않고(-1), EN이 실패하면 KO만 저장한다. 프롬프트, max_tokens
  8192, temperature 0.1은 그대로다.
- 스트림이 열린 뒤 끊기면(청크 사이 read timeout, 연결 끊김, 스트림 안의 오류 이벤트) 남은 예산이 _RETRY_MIN_S 이상일 때만 한
  번 다시 부른다. 끊긴 시도의 부분 텍스트는 버린다. wall-clock 만료는 다시 부르지 않는다.
- CLI 태스크 예산(INSIGHTS_TASK_BUDGET_S, 기본 240초): 호출 상한은 min(180초, 마감 − 지금 − 저장 여유 15초)이고, 예산 + 15초에
  백스톱 타이머가 exit 1로 프로세스를 끝낸다. 정상 종료도 os._exit다(멈춘 워커가 태스크를 RUNNING으로 붙잡지 않게).
  backend의 /regenerate 스레드에는 마감이 없다(호출 상한 180초만).
- 언어마다 소요 시간, output_tokens, input_tokens, stop_reason을 INFO로 남기고, max_tokens에서 멈추면 WARNING이다.

가짜 Bedrock(tests/_fake_bedrock.py)은 로컬 소켓 서버이고 실제 boto3 client가 AWS_ENDPOINT_URL_BEDROCK_RUNTIME으로 붙는다.
시간은 줄여서 본다: read timeout 60초 → 0.5초. 생성 70초(운영 EN p50)는 0.25초 간격 델타 6개(1.5초)다.
"""

import os
import re
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import boto3
import botocore.exceptions
import pytest
from botocore.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import agent.bedrock
import insights_runner
import models
from tests._fake_bedrock import Blocking, FakeBedrock, Silent, Stream
from tests._read_dataset import FROZEN_NOW, FrozenDatetime, seed

BACKEND = Path(__file__).resolve().parents[1]
READ_TIMEOUT_S = 0.5  # 운영 60초
KO = [f"요약 {i}. " for i in range(6)]
EN = [f"summary {i}. " for i in range(6)]
SLOW = 0.25  # 델타 간격 — read timeout보다 짧고, 6개면 1.5초로 read timeout의 세 배


@pytest.fixture()
def dataset(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    seed(factory)
    monkeypatch.setattr(insights_runner, "datetime", FrozenDatetime)
    monkeypatch.setattr(insights_runner, "SessionLocal", factory)
    try:
        yield factory
    finally:
        engine.dispose()


# 지우는 env — 프로필, 재시도 모드와 횟수, defaults_mode(connect_timeout과 재시도 모드를 바꾼다)는 client 설정을, 세션
# 토큰과 AWS_IGNORE_CONFIGURED_ENDPOINT_URLS는 가짜 Bedrock 연결(서명, endpoint)을 바꾼다.
_AWS_ENV_UNSET = ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_RETRY_MODE", "AWS_MAX_ATTEMPTS", "AWS_DEFAULTS_MODE",
                  "AWS_SESSION_TOKEN", "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS")


def _isolate_aws(monkeypatch, tmp_path) -> None:
    """개발자 머신의 AWS 설정을 읽지 않는 boto3 — 어느 머신에서나 같은 client 설정이 나온다.

    설정 파일과 자격 증명 파일은 없는 경로로, 위 env는 지운다. 기본 session도 새로 만든다(앞 테스트가 다른 env로 만든
    session을 쓰지 않게).
    """
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    for name in _AWS_ENV_UNSET:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(boto3, "DEFAULT_SESSION", None)


@pytest.fixture()
def fake(monkeypatch, tmp_path):
    _isolate_aws(monkeypatch, tmp_path)
    server = FakeBedrock()
    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", server.url)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret-for-a-local-socket")
    monkeypatch.setattr(agent.bedrock, "INSIGHTS_READ_TIMEOUT_S", READ_TIMEOUT_S)
    monkeypatch.setattr(agent.bedrock, "INSIGHTS_CONNECT_TIMEOUT_S", READ_TIMEOUT_S)
    try:
        yield server
    finally:
        server.close()


def _saved(factory) -> list:
    with factory() as db:
        return db.query(models.Insight).order_by(models.Insight.id).all()


def _only_saved(factory):
    rows = _saved(factory)
    assert len(rows) == 1, rows
    return rows[0]


# ───────────────────────────────────────────────────────────────────────
# 전용 client — 챗봇 client는 그대로
# ───────────────────────────────────────────────────────────────────────


def _developer_aws_setup(monkeypatch, tmp_path) -> None:
    """개발자 머신에 있을 법한 AWS 설정. 격리하지 않으면 챗봇 client의 재시도 모드, 횟수, connect_timeout이 바뀐다.

    botocore는 자격 증명 파일의 프로필 키도 설정에 합친다 — 그래서 자격 증명 파일의 [default]에 둔 max_attempts도 client에 간다.
    """
    config = tmp_path / "developer-config"
    config.write_text("[default]\nretry_mode = adaptive\nmax_attempts = 7\n"
                      "[profile dev]\nretry_mode = standard\nmax_attempts = 3\ndefaults_mode = standard\n")
    credentials = tmp_path / "developer-credentials"
    credentials.write_text("[default]\naws_access_key_id = AKIDEXAMPLE\naws_secret_access_key = developer-secret\n"
                           "max_attempts = 4\n"
                           "[dev]\naws_access_key_id = AKIDEXAMPLE\naws_secret_access_key = developer-secret\n")
    env = {"AWS_CONFIG_FILE": str(config), "AWS_SHARED_CREDENTIALS_FILE": str(credentials), "AWS_PROFILE": "dev",
           "AWS_DEFAULT_PROFILE": "dev", "AWS_RETRY_MODE": "adaptive", "AWS_MAX_ATTEMPTS": "9",
           "AWS_DEFAULTS_MODE": "standard"}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(boto3, "DEFAULT_SESSION", boto3.Session())  # 앞 테스트가 이 설정으로 만들어 둔 기본 session


@pytest.mark.parametrize("developer_aws", [False, True], ids=["host-aws-setup", "developer-aws-setup"])
def test_insights_client_is_dedicated_and_the_chat_client_is_unchanged(monkeypatch, tmp_path, developer_aws):
    if developer_aws:
        _developer_aws_setup(monkeypatch, tmp_path)
    _isolate_aws(monkeypatch, tmp_path)
    client = agent.bedrock.insights_client()
    cfg = client.meta.config
    assert (cfg.connect_timeout, cfg.read_timeout) == (10, 60)
    assert cfg.retries == {"mode": "standard", "total_max_attempts": 2}  # legacy 기본값은 5회
    assert client.meta.region_name == "ap-northeast-2"
    chat = agent.bedrock._client().meta.config  # 챗봇, follow-up, stream-regenerate
    assert (chat.connect_timeout, chat.read_timeout, chat.retries) == (60, 60, {"mode": "legacy"})


def test_the_blocking_converse_times_out_on_a_generation_longer_than_the_read_timeout(fake):
    """전제 확인 — 운영의 실패 경로. 비스트림 converse는 생성이 끝나야 첫 바이트가 와서 read timeout에 걸린다."""
    fake.scripts["en"] = [Blocking("summary", delay_s=1.5), Blocking("summary", delay_s=1.5)]
    client = boto3.client("bedrock-runtime", region_name="ap-northeast-2", config=Config(
        read_timeout=READ_TIMEOUT_S, connect_timeout=READ_TIMEOUT_S, retries={"mode": "standard", "total_max_attempts": 2}))
    with pytest.raises(botocore.exceptions.ReadTimeoutError):
        client.converse(modelId=agent.bedrock.INSIGHTS_MODEL_ID, system=[{"text": "english"}],
                        messages=[{"role": "user", "content": [{"text": "hi"}]}])
    assert len(fake.by_lang("en")) == 2


# ───────────────────────────────────────────────────────────────────────
# read timeout보다 긴 생성, 동시 실행, 저장 모양
# ───────────────────────────────────────────────────────────────────────


def test_a_generation_longer_than_the_read_timeout_is_saved_in_both_languages(dataset, fake):
    fake.scripts = {"ko": [Stream(KO, gap_s=SLOW)], "en": [Stream(EN, gap_s=SLOW)]}
    insight_id = insights_runner.run_once("6h")
    assert insight_id > 0
    saved = _only_saved(dataset)
    assert saved.id == insight_id
    assert (saved.summary_md, saved.summary_md_en) == ("".join(KO), "".join(EN))
    # 저장 모양은 그대로 — 창, 통계
    assert saved.window_end.replace(tzinfo=None) == FROZEN_NOW.replace(tzinfo=None)
    assert (saved.window_end - saved.window_start).total_seconds() == 6 * 3600
    assert saved.model_breakdown and all(set(m) == {"total", "errors", "error_rate", "ttft_ms", "total_latency_ms",
                                                    "tps"} for m in saved.model_breakdown.values())
    # 스트림으로만 받았다 — 비스트림 converse(60초 read timeout 경로)는 부르지 않는다
    assert fake.paths() == [f"/model/{agent.bedrock.INSIGHTS_MODEL_ID}/converse-stream"] * 2
    assert [r.outcome for r in fake.requests] == ["completed", "completed"]


def test_requests_carry_the_unchanged_prompts_and_inference_config(dataset, fake):
    insights_runner.run_once("6h")
    saved = _only_saved(dataset)
    for lang in ("ko", "en"):
        (req,) = fake.by_lang(lang)
        system, user_text = insights_runner._build_prompt("6h", saved.model_breakdown, lang)
        assert req.body["system"] == [{"text": system}]
        assert req.body["messages"] == [{"role": "user", "content": [{"text": user_text}]}]
        assert req.body["inferenceConfig"] == {"maxTokens": 8192, "temperature": 0.1}


def test_ko_and_en_are_generated_concurrently(dataset, fake):
    fake.scripts = {"ko": [Stream(KO, gap_s=SLOW)], "en": [Stream(EN, gap_s=SLOW)]}
    started = time.monotonic()
    assert insights_runner.run_once("6h") > 0
    elapsed = time.monotonic() - started
    (ko,), (en,) = fake.by_lang("ko"), fake.by_lang("en")
    assert max(ko.started, en.started) < min(ko.finished, en.finished)  # 두 생성이 겹쳤다
    assert elapsed < 2 * len(KO) * SLOW  # 순서대로면 3초 이상


# ───────────────────────────────────────────────────────────────────────
# 재시도 — 헤더 대기는 botocore가 한 번, 스트림이 열린 뒤 끊기면 러너가 한 번(예산이 있을 때)
# ───────────────────────────────────────────────────────────────────────


def test_a_header_wait_timeout_is_retried_once(dataset, fake):
    fake.scripts = {"ko": [Stream(KO)], "en": [Silent(), Stream(EN)]}
    assert insights_runner.run_once("6h") > 0
    assert _only_saved(dataset).summary_md_en == "".join(EN)
    assert [r.outcome for r in fake.by_lang("en")] == ["silent", "completed"]


def test_two_header_wait_timeouts_stop_after_two_attempts_and_save_ko_only(dataset, fake, caplog):
    fake.scripts = {"ko": [Stream(KO)], "en": [Silent(), Silent(), Stream(EN)]}
    with caplog.at_level("INFO"):
        assert insights_runner.run_once("6h") > 0
    saved = _only_saved(dataset)
    assert (saved.summary_md, saved.summary_md_en) == ("".join(KO), None)
    assert len(fake.by_lang("en")) == 2  # legacy 기본값이면 5회
    assert "EN insight generation failed; KO만 저장" in caplog.text


def test_a_mid_stream_stall_is_retried_once_and_the_partial_text_is_dropped(dataset, fake, caplog):
    fake.scripts = {"ko": [Stream(KO)], "en": [Stream(["부분 텍스트 "] * 4, stall_after=2), Stream(EN)]}
    with caplog.at_level("WARNING", logger="insights_runner"):
        assert insights_runner.run_once("6h") > 0
    assert _only_saved(dataset).summary_md_en == "".join(EN)  # 끊긴 시도의 앞부분은 붙지 않는다
    assert [r.outcome for r in fake.by_lang("en")] == ["stalled", "completed"]
    assert re.search(r"insights summary en: .*interrupted.* retrying \(attempt 2/2\)", caplog.text), caplog.text


def test_a_mid_stream_stall_is_not_retried_when_the_budget_is_short(dataset, fake, monkeypatch, caplog):
    monkeypatch.setattr(insights_runner, "_SAVE_MARGIN_S", 0.1)
    monkeypatch.setattr(insights_runner, "_MIN_CALL_S", 0.1)
    monkeypatch.setattr(insights_runner, "_RETRY_MIN_S", 30.0)  # 남은 예산 5초 < 30초
    fake.scripts = {"ko": [Stream(KO)], "en": [Stream(["부분 "] * 4, stall_after=1), Stream(EN)]}
    with caplog.at_level("INFO"):
        assert insights_runner.run_once("6h", deadline=time.monotonic() + 5) > 0
    assert _only_saved(dataset).summary_md_en is None
    assert [r.outcome for r in fake.by_lang("en")] == ["stalled"]
    assert "EN insight generation failed; KO만 저장" in caplog.text


def test_a_failed_ko_summary_saves_nothing(dataset, fake, caplog):
    fake.scripts = {"ko": [Silent(), Silent()], "en": [Stream(EN)]}
    with caplog.at_level("INFO"):
        assert insights_runner.run_once("6h") == -1
    assert _saved(dataset) == []
    assert "insights_runner 실패" in caplog.text


# ───────────────────────────────────────────────────────────────────────
# wall-clock 상한과 태스크 예산
# ───────────────────────────────────────────────────────────────────────


def _trickle(n: int = 200) -> Stream:
    """청크 사이는 0.1초라 read timeout(0.5초)은 끝내 걸리지 않고, 끝까지 20초 — 드문드문 흐르는 스트림."""
    return Stream(["x"] * n, gap_s=0.1)


def _wait_outcome(req, expected: str, timeout_s: float = 3.0) -> str:
    deadline = time.monotonic() + timeout_s
    while req.outcome != expected and time.monotonic() < deadline:
        time.sleep(0.02)
    return req.outcome


def test_the_wall_clock_cap_cuts_a_trickling_stream_and_ko_is_kept(dataset, fake, monkeypatch, caplog):
    monkeypatch.setattr(insights_runner, "INSIGHTS_CALL_WALL_CLOCK_S", 1.0)
    monkeypatch.setattr(insights_runner, "_MIN_CALL_S", 0.1)
    fake.scripts = {"ko": [Stream(KO)], "en": [_trickle(), Stream(EN)]}
    started = time.monotonic()
    with caplog.at_level("INFO"):
        assert insights_runner.run_once("6h") > 0
    assert time.monotonic() - started < 3.0  # 20초짜리 스트림을 1초 근처에서 끊었다
    assert _only_saved(dataset).summary_md_en is None
    (en,) = fake.by_lang("en")  # 만료는 다시 부르지 않는다
    assert _wait_outcome(en, "aborted") == "aborted" and en.sent_deltas < 20  # 소켓을 끊었다
    assert "exceeded the 1s wall-clock limit" in caplog.text


def test_the_call_limit_is_the_cap_or_the_budget_left_minus_the_save_margin(monkeypatch):
    monkeypatch.setattr(insights_runner, "_clock", lambda: 1000.0)
    assert insights_runner._call_limit(None) == 180  # /regenerate 스레드 — 마감 없음
    assert insights_runner._call_limit(1000.0 + 240) == 180  # 240 − 15 = 225초 남음, 상한 180초가 더 짧다
    assert insights_runner._call_limit(1000.0 + 100) == 85  # 100 − 15


def test_the_call_limit_shrinks_to_the_task_budget(dataset, fake, monkeypatch, caplog):
    """호출 상한(마감 − 지금 − 저장 여유)이 워치독까지 가서 스트림을 끊는다.

    _result는 마감에서 워커를 포기하므로 run_once의 반환값과 소요 시간만 보면 상한이 마감을 무시해도(180초) 통과한다. 그래서
    converse_stream_collect에 넘어간 wall_clock_s를 직접 보고, KO를 끝낸 것이 마감 대기가 아니라 워치독(StreamWallClockTimeout,
    마감 0.5초 전)인지 본다.
    """
    margin = 0.5
    monkeypatch.setattr(insights_runner, "_SAVE_MARGIN_S", margin)
    monkeypatch.setattr(insights_runner, "_MIN_CALL_S", 0.1)
    fake.scripts = {"ko": [_trickle()], "en": [_trickle()]}
    started = time.monotonic()
    deadline = started + 2.0
    calls: list[tuple[str, float, float]] = []  # (system, 넘어간 상한, 그 시각의 마감 − 지금 − 저장 여유)
    collect = agent.bedrock.converse_stream_collect

    def spy(messages, **kw):
        calls.append((kw["system"], kw["wall_clock_s"], deadline - time.monotonic() - margin))
        return collect(messages, **kw)

    monkeypatch.setattr(agent.bedrock, "converse_stream_collect", spy)
    with caplog.at_level("INFO"):
        assert insights_runner.run_once("6h", deadline=deadline) == -1  # 상한 약 1.5초 → KO 실패
    assert time.monotonic() - started < 2.0 + 0.5  # 마감 안에 끝났다
    assert _saved(dataset) == []
    # 두 언어 모두 상한이 예산 크기로 줄었다 — 180초도, 저장 여유를 빼지 않은 2초도 아니다
    assert sorted(system for system, _, _ in calls) == sorted([insights_runner.SUMMARY_SYSTEM_KO,
                                                               insights_runner.SUMMARY_SYSTEM_EN])
    for _, limit, budget_left in calls:
        assert limit == pytest.approx(budget_left, abs=0.05)
    # 그 상한에서 워치독이 KO 소켓을 끊었다 — 마감에서 워커를 포기한 것이 아니다
    (ko,) = fake.by_lang("ko")
    assert _wait_outcome(ko, "aborted") == "aborted" and ko.sent_deltas < 20
    assert re.search(r"insights summary ko failed after \d+\.\ds \(attempt 1\): StreamWallClockTimeout", caplog.text), \
        caplog.text
    assert "did not finish before the task deadline" not in caplog.text


def test_a_header_wait_past_the_deadline_is_abandoned_and_ko_is_saved(dataset, fake, monkeypatch, caplog):
    """wall-clock 상한은 스트림이 열린 뒤에만 끊는다. 헤더 대기(read timeout × botocore 2회)가 마감을 넘기면 러너는 마감에서
    EN을 포기하고 KO를 저장한다 — 백스톱(exit 1)까지 가서 KO까지 잃지 않는다."""
    monkeypatch.setattr(agent.bedrock, "INSIGHTS_READ_TIMEOUT_S", 1.0)  # 헤더 대기 2회 = 2초 이상
    monkeypatch.setattr(insights_runner, "_SAVE_MARGIN_S", 0.1)
    monkeypatch.setattr(insights_runner, "_MIN_CALL_S", 0.1)
    fake.scripts = {"ko": [Stream(KO)], "en": [Silent(), Silent()]}
    started = time.monotonic()
    with caplog.at_level("INFO"):
        assert insights_runner.run_once("6h", deadline=started + 0.8) > 0
    assert time.monotonic() - started < 1.5
    saved = _only_saved(dataset)
    assert (saved.summary_md, saved.summary_md_en) == ("".join(KO), None)
    assert "en summary did not finish before the task deadline" in caplog.text


def test_no_bedrock_call_once_the_budget_is_spent(dataset, fake):
    assert insights_runner.run_once("6h", deadline=time.monotonic() - 1) == -1
    assert fake.requests == [] and _saved(dataset) == []


# ───────────────────────────────────────────────────────────────────────
# 로그 — 언어별 소요 시간, 출력 토큰
# ───────────────────────────────────────────────────────────────────────


def test_each_language_logs_duration_output_tokens_and_stop_reason(dataset, fake, caplog):
    fake.scripts = {"ko": [Stream(KO, output_tokens=5386)],
                    "en": [Stream(EN, output_tokens=8192, stop_reason="max_tokens")]}
    with caplog.at_level("INFO", logger="insights_runner"):
        assert insights_runner.run_once("6h") > 0
    saved = _only_saved(dataset)
    assert (saved.summary_md, saved.summary_md_en) == ("".join(KO), "".join(EN))  # 잘린 요약도 지금처럼 저장한다
    text = caplog.text
    assert re.search(r"insights summary ko: \d+\.\d+s, output_tokens=5386, input_tokens=1500, stop_reason=end_turn, "
                     rf"chars={len(''.join(KO))}, attempts=1", text), text
    assert re.search(r"insights summary en: \d+\.\d+s, output_tokens=8192, .*stop_reason=max_tokens", text), text
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert [r.getMessage() for r in warnings] == [
        "insights summary en stopped at max_tokens (8192), the saved summary may be cut off"]


# ───────────────────────────────────────────────────────────────────────
# CLI — 예산 마감, 백스톱, os._exit
# ───────────────────────────────────────────────────────────────────────


def test_main_hands_run_once_the_task_budget_deadline(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(insights_runner, "run_once",
                        lambda window_spec="6h", *, deadline=None: seen.update(window=window_spec, deadline=deadline) or 7)
    monkeypatch.setattr(sys, "argv", ["insights_runner", "--window", "6h"])
    started = time.monotonic() - 3.0  # 프로세스가 3초 전에 떴다
    assert insights_runner.main(started_at=started) == 0
    assert seen == {"window": "6h", "deadline": pytest.approx(started + insights_runner.INSIGHTS_TASK_BUDGET_S)}
    assert insights_runner.INSIGHTS_TASK_BUDGET_S == 240 and insights_runner.INSIGHTS_CALL_WALL_CLOCK_S == 180


def test_the_backstop_exits_1_once_the_budget_and_grace_pass(monkeypatch, caplog):
    exits: list[int] = []
    release = threading.Event()

    def hard_exit(code):
        exits.append(code)
        release.set()

    monkeypatch.setattr(insights_runner, "_hard_exit", hard_exit)
    monkeypatch.setattr(insights_runner, "INSIGHTS_TASK_BUDGET_S", 0.2)
    monkeypatch.setattr(insights_runner, "_BACKSTOP_GRACE_S", 0.1)
    monkeypatch.setattr(insights_runner, "run_once", lambda window_spec="6h", *, deadline=None: release.wait(5) and 0)
    monkeypatch.setattr(sys, "argv", ["insights_runner"])
    started = time.monotonic()
    with caplog.at_level("ERROR", logger="insights_runner"):
        insights_runner.main(started_at=started)
    assert exits == [1] and time.monotonic() - started < 2.0
    assert "insights_runner: task budget 0.2s + 0.1s grace passed, exiting 1" in caplog.text


def test_the_backstop_is_cancelled_when_main_returns(monkeypatch):
    exits: list[int] = []
    monkeypatch.setattr(insights_runner, "_hard_exit", exits.append)
    monkeypatch.setattr(insights_runner, "INSIGHTS_TASK_BUDGET_S", 0.1)
    monkeypatch.setattr(insights_runner, "_BACKSTOP_GRACE_S", 0.1)
    monkeypatch.setattr(insights_runner, "run_once", lambda window_spec="6h", *, deadline=None: 0)
    monkeypatch.setattr(sys, "argv", ["insights_runner"])
    assert insights_runner.main() == 0
    time.sleep(0.5)
    assert exits == []


_ENTRYPOINT = textwrap.dedent("""
    import runpy, sys, threading
    from datetime import datetime, timezone
    import database, models
    from agent import bedrock

    database.create_tables()
    with database.SessionLocal() as db:
        now = datetime.now(timezone.utc)
        db.add(models.ProbeRun(id=1, prompt="auto", status="completed", is_auto=1, created_at=now))
        db.add(models.ProbeResult(run_id=1, model_id="m", model_name="Bedrock M (Global)", status="success",
                                  prompt="p", timestamp=now, ttft_ms=100.0, total_latency_ms=900.0, tps=50.0))
        db.commit()

    MODE = sys.argv[1]
    if MODE == "stuck-worker":
        def client():
            threading.Thread(target=threading.Event().wait, daemon=False).start()  # 영원히 안 끝나는 워커
            return object()
        bedrock.insights_client = client
        bedrock.converse_stream_collect = lambda messages, **kw: bedrock.StreamedText(
            text="요약", stop_reason="end_turn", input_tokens=1, output_tokens=1, elapsed_s=0.0)
        sys.argv = ["insights_runner", "--window", "6h"]
        runpy.run_module("insights_runner", run_name="__main__")  # python -m insights_runner 그대로
    else:  # hung-call — 요약이 끝나지 않는다(헤더 대기에서 멈춘 client). 예산을 줄이려고 모듈을 import해 같은 진입 함수를 부른다
        bedrock.insights_client = lambda: threading.Event().wait()
        import insights_runner
        insights_runner.INSIGHTS_TASK_BUDGET_S = 0.3
        insights_runner._BACKSTOP_GRACE_S = 0.2
        sys.argv = ["insights_runner", "--window", "6h"]
        insights_runner._entrypoint()
    print("UNREACHABLE: the entrypoint must end the process")
""")


def _run_entrypoint(mode: str, tmp_path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _ENTRYPOINT, mode], cwd=BACKEND, capture_output=True, text=True, timeout=60,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'insights.db'}", "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_module_entrypoint_exits_promptly_despite_a_stuck_worker_thread(tmp_path):
    started = time.monotonic()
    proc = _run_entrypoint("stuck-worker", tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "UNREACHABLE" not in proc.stdout
    assert "insights_runner: insight id=1 저장 (window=6h)" in proc.stderr  # 로그가 os._exit 전에 flush됐다
    assert time.monotonic() - started < 30


def test_module_entrypoint_backstop_ends_a_hung_summary_with_exit_1(tmp_path):
    started = time.monotonic()
    proc = _run_entrypoint("hung-call", tmp_path)
    assert proc.returncode == 1, proc.stderr[-2000:]
    assert "UNREACHABLE" not in proc.stdout
    assert "insights_runner: task budget 0.3s + 0.2s grace passed, exiting 1" in proc.stderr
    assert time.monotonic() - started < 30
