"""Regression test for the backend DB connection-pool exhaustion outage.

Root cause (2026-07-08 incident): ~10 worker threads blocked forever on reads from
DB connections whose TCP peer had silently died (RDS-side connections dropped to ~0
while the backend pool stayed "checked out"). Without TCP keepalive or a runtime
statement_timeout the threads never got an error, the connections were never
invalidated, and the pool (5+5=10) stayed permanently exhausted — every DB endpoint
returned 500 after pool_timeout=10s until the task was manually restarted.
pool_recycle/pool_pre_ping cannot help here: both only act on connections that are
*returned to* / *checked out from* the pool, never on ones already checked out.

This test pins the libpq-level safeguards so they are not accidentally dropped.
"""

import database


def test_pg_connect_args_enable_tcp_keepalive():
    args = database._PG_CONNECT_ARGS
    assert args["keepalives"] == 1
    # 죽은 소켓 감지 상한 ≈ idle + interval×count = 60s. 과도하게 길어지지 않게 고정.
    assert args["keepalives_idle"] + args["keepalives_interval"] * args["keepalives_count"] <= 120


def test_pg_connect_args_bound_query_and_connect_time():
    args = database._PG_CONNECT_ARGS
    assert "statement_timeout=" in args["options"]
    assert int(args["options"].split("statement_timeout=")[1]) > 0
    assert args["connect_timeout"] > 0


def test_engine_keeps_pool_safeguards():
    # 기존 안전장치 회귀 방지 (pre_ping은 체크아웃 시점 죽은 커넥션 감지).
    assert database.engine.pool._pre_ping is True
    assert database.engine.pool.size() == 5
    assert database.engine.pool._max_overflow == 5
    assert database.engine.pool._timeout == 10
