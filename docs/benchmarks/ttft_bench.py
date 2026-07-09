#!/usr/bin/env python3
"""TTFB / TTFT benchmark for GPT-5.x on Bedrock Mantle (OpenAI Responses API).

Companion script for docs/benchmarks/2026-06-26-openai-gpt-ttfb-ttft.md.
This is the exact script used to produce that report's numbers.

Metrics
  TTFB  = time to first stream event (response.created) — first byte from server.
  TTFT  = time to first response.output_text.delta — first visible TEXT chunk,
          which for a reasoning model is AFTER the thinking (reasoning) phase.
  gap   = TTFT - TTFB  ≈ server-side reasoning/thinking time.

Covers all monitored OpenAI regions × their available models (per-region availability:
gpt-5.5 is NOT served in us-west-2). It replicates the requested body params exactly via
extra_body (verbosity=low, reasoning effort=medium, include reasoning.encrypted_content,
store=False, max_output_tokens=4096, prompt_cache_retention=24h). `tools` omitted (was not
provided). The prompt is a synthetic ~55k-token context held FIXED across calls so
prompt-cache engages; 1 warm-up call primes the cache, then RUNS measured calls.

Measurements are SEQUENTIAL on purpose — running regions/models in parallel would cause
network/API contention that distorts latency. Do not parallelize a latency benchmark.

Prerequisites
  - pip install --user openai
  - AWS creds with ssm:GetParameter (+kms decrypt) on /bedrock-monitor/openai-api-key
  - SSM SecureString /bedrock-monitor/openai-api-key holding a Bedrock long-term API key

Run
  python3 docs/benchmarks/ttft_bench.py

Caveats (see report §9)
  - Synthetic prompt + no tools → not a byte-exact reproduction of a real request.
  - TTFB is vantage-point dependent (here: ap-northeast-2 EC2 → each region's endpoint).
  - prompt cache is best-effort; cached_tokens varies run to run.
"""
import subprocess, sys, time, statistics

RUNS = 10
INSTRUCTIONS = "You are a precise technical assistant. Answer in one short sentence."

# region -> base_url
REGIONS = {
    "us-east-1": "https://bedrock-mantle.us-east-1.api.aws/openai/v1",
    "us-east-2": "https://bedrock-mantle.us-east-2.api.aws/openai/v1",
    "us-west-2": "https://bedrock-mantle.us-west-2.api.aws/openai/v1",
}
# per-region available models (gpt-5.5 is not served in us-west-2)
REGION_MODELS = {
    "us-east-1": ["openai.gpt-5.4", "openai.gpt-5.5"],
    "us-east-2": ["openai.gpt-5.4", "openai.gpt-5.5"],
    "us-west-2": ["openai.gpt-5.4"],
}

# --- key from SSM (never printed; fetched in-process, not on a command line) ---
r = subprocess.run(["aws", "ssm", "get-parameter", "--region", "ap-northeast-2",
                    "--name", "/bedrock-monitor/openai-api-key", "--with-decryption",
                    "--query", "Parameter.Value", "--output", "text"],
                   capture_output=True, text=True)
if r.returncode != 0:
    print("SSM fetch failed:", r.stderr[:200]); sys.exit(1)
KEY = r.stdout.strip()

# --- build ~55k-token static context (deterministic, fixed → cacheable) ---
PARA = ("In distributed observability, tail latency dominates user-perceived performance; "
        "time-to-first-byte and time-to-first-token diverge sharply for reasoning models "
        "because the server emits an acknowledgment before it finishes its hidden chain of "
        "thought, and only afterwards streams the first visible text delta to the client. ")
BIG = "".join(f"[Section {i:04d}] {PARA}" for i in range(900))  # ~55k tokens
INPUT = [{"role": "user", "content": BIG +
          "\n\nQuestion: In one sentence, what is the single most important idea above?"}]

EXTRA = {
    "text": {"format": {"type": "text"}, "verbosity": "low"},
    "reasoning": {"effort": "medium"},
    "include": ["reasoning.encrypted_content"],
    "store": False,
    "prompt_cache_retention": "24h",
}

from openai import OpenAI

_clients = {}
def client_for(region):
    if region not in _clients:
        _clients[region] = OpenAI(api_key=KEY, base_url=REGIONS[region])
    return _clients[region]


def one_call(region, model):
    client = client_for(region)
    t0 = time.perf_counter()
    ttfb = ttft = None
    cached = reasoning = out = inp = None
    err = None
    try:
        stream = client.responses.create(model=model, input=INPUT, instructions=INSTRUCTIONS,
                                          max_output_tokens=4096, stream=True, extra_body=EXTRA)
        for ev in stream:
            now = time.perf_counter()
            et = getattr(ev, "type", "")
            if ttfb is None:
                ttfb = (now - t0) * 1000.0
            if et == "response.output_text.delta" and ttft is None:
                ttft = (now - t0) * 1000.0
            if et in ("response.completed", "response.incomplete", "response.failed"):
                u = getattr(getattr(ev, "response", None), "usage", None)
                if u is not None:
                    inp = getattr(u, "input_tokens", None)
                    out = getattr(u, "output_tokens", None)
                    itd = getattr(u, "input_tokens_details", None)
                    cached = getattr(itd, "cached_tokens", None) if itd else None
                    otd = getattr(u, "output_tokens_details", None)
                    reasoning = getattr(otd, "reasoning_tokens", None) if otd else None
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:140]}"
    return dict(ttfb=ttfb, ttft=ttft, cached=cached, reasoning=reasoning, out=out, inp=inp, err=err)


def _(x):
    return f"{x:7.1f}" if x is not None else "  n/a  "


def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return dict(min=min(vals), median=statistics.median(vals),
                mean=statistics.mean(vals), max=max(vals))


def fmt(s):
    return "n/a" if s is None else (f"min {s['min']:7.1f} | median {s['median']:7.1f} | "
                                    f"mean {s['mean']:7.1f} | max {s['max']:7.1f}")


matrix = []  # (region, model, ttfb_stats, ttft_stats, gap_stats)
for region, models in REGION_MODELS.items():
    for model in models:
        print(f"\n################  {model}  @ {region}  ################")
        warm = one_call(region, model)
        print(f"warm-up: ttfb={warm['ttfb']} ttft={warm['ttft']} input_tokens={warm['inp']} "
              f"cached={warm['cached']} reasoning={warm['reasoning']} err={warm['err']}")
        rows = []
        for i in range(1, RUNS + 1):
            rr = one_call(region, model)
            rows.append(rr)
            gap = (rr["ttft"] - rr["ttfb"]) if (rr["ttft"] and rr["ttfb"]) else None
            print(f"run {i:2d}: TTFB={_(rr['ttfb'])}ms  TTFT={_(rr['ttft'])}ms  "
                  f"gap={_(gap)}ms  cached={rr['cached']}/{rr['inp']}  "
                  f"reasoning_tok={rr['reasoning']}  out={rr['out']}"
                  + (f"  ERR={rr['err']}" if rr['err'] else ""))
        st_ttfb = stats([r['ttfb'] for r in rows])
        st_ttft = stats([r['ttft'] for r in rows])
        st_gap = stats([(r['ttft'] - r['ttfb']) for r in rows if r['ttft'] and r['ttfb']])
        print(f"  TTFB(ms): {fmt(st_ttfb)}")
        print(f"  TTFT(ms): {fmt(st_ttft)}")
        print(f"  GAP (ms): {fmt(st_gap)}")
        matrix.append((region, model, st_ttfb, st_ttft, st_gap))

print("\n================  SUMMARY MATRIX (median ms)  ================")
print(f"{'region':<11} {'model':<16} {'TTFB':>8} {'TTFT':>8} {'GAP':>8}")
for region, model, a, b, g in matrix:
    print(f"{region:<11} {model:<16} "
          f"{(a['median'] if a else 0):>8.0f} {(b['median'] if b else 0):>8.0f} "
          f"{(g['median'] if g else 0):>8.0f}")
