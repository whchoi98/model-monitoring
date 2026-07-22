#!/usr/bin/env python3
"""TTFB / TTFT re-benchmark (2026-07-06): Bedrock Mantle 5 channels + 1P direct 2 channels.

Based on docs/benchmarks/ttft_bench.py (2026-06-26 methodology, unchanged):
  TTFB = first stream event; TTFT = first response.output_text.delta; gap = thinking time.
  ~55k-token fixed prompt (cacheable), 1 warm-up + RUNS measured calls, SEQUENTIAL.

Changes vs original: RUNS 10 -> 20, adds 1P direct (api.openai.com) gpt-5.4 AND gpt-5.5
using the production platform key from SSM /bedrock-monitor/openai-1p-api-key (v2.6.0).
"""
import subprocess, sys, time, statistics

RUNS = 20
INSTRUCTIONS = "You are a precise technical assistant. Answer in one short sentence."

def ssm_get(name):
    r = subprocess.run(["aws", "ssm", "get-parameter", "--region", "ap-northeast-2",
                        "--name", name, "--with-decryption",
                        "--query", "Parameter.Value", "--output", "text"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"SSM fetch failed for {name}:", r.stderr[:200]); sys.exit(1)
    return r.stdout.strip()

MANTLE_KEY = ssm_get("/bedrock-monitor/openai-api-key")

# (channel_label, base_url, api_key, model)
CHANNELS = [
    ("mantle us-east-1", "https://bedrock-mantle.us-east-1.api.aws/openai/v1", MANTLE_KEY, "openai.gpt-5.4"),
    ("mantle us-east-1", "https://bedrock-mantle.us-east-1.api.aws/openai/v1", MANTLE_KEY, "openai.gpt-5.5"),
    ("mantle us-east-2", "https://bedrock-mantle.us-east-2.api.aws/openai/v1", MANTLE_KEY, "openai.gpt-5.4"),
    ("mantle us-east-2", "https://bedrock-mantle.us-east-2.api.aws/openai/v1", MANTLE_KEY, "openai.gpt-5.5"),
    ("mantle us-west-2", "https://bedrock-mantle.us-west-2.api.aws/openai/v1", MANTLE_KEY, "openai.gpt-5.4"),
]

# --- ~55k-token static context, identical to the 2026-06-26 run (fixed -> cacheable) ---
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
def client_for(base_url, key):
    if base_url not in _clients:
        _clients[base_url] = OpenAI(api_key=key, base_url=base_url)
    return _clients[base_url]


def one_call(base_url, key, model):
    client = client_for(base_url, key)
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


matrix = []
for label, base_url, key, model in CHANNELS:
    print(f"\n################  {model}  @ {label}  ################", flush=True)
    warm = one_call(base_url, key, model)
    print(f"warm-up: ttfb={warm['ttfb']} ttft={warm['ttft']} input_tokens={warm['inp']} "
          f"cached={warm['cached']} reasoning={warm['reasoning']} err={warm['err']}", flush=True)
    rows = []
    for i in range(1, RUNS + 1):
        rr = one_call(base_url, key, model)
        rows.append(rr)
        gap = (rr["ttft"] - rr["ttfb"]) if (rr["ttft"] and rr["ttfb"]) else None
        print(f"run {i:2d}: TTFB={_(rr['ttfb'])}ms  TTFT={_(rr['ttft'])}ms  "
              f"gap={_(gap)}ms  cached={rr['cached']}/{rr['inp']}  "
              f"reasoning_tok={rr['reasoning']}  out={rr['out']}"
              + (f"  ERR={rr['err']}" if rr['err'] else ""), flush=True)
    st_ttfb = stats([r['ttfb'] for r in rows])
    st_ttft = stats([r['ttft'] for r in rows])
    st_gap = stats([(r['ttft'] - r['ttfb']) for r in rows if r['ttft'] and r['ttfb']])
    print(f"  TTFB(ms): {fmt(st_ttfb)}", flush=True)
    print(f"  TTFT(ms): {fmt(st_ttft)}", flush=True)
    print(f"  GAP (ms): {fmt(st_gap)}", flush=True)
    matrix.append((label, model, st_ttfb, st_ttft, st_gap))

print("\n================  SUMMARY MATRIX (median ms, N=20)  ================")
print(f"{'channel':<18} {'model':<16} {'TTFB':>8} {'TTFT':>8} {'GAP':>8}")
for label, model, a, b, g in matrix:
    print(f"{label:<18} {model:<16} "
          f"{(a['median'] if a else 0):>8.0f} {(b['median'] if b else 0):>8.0f} "
          f"{(g['median'] if g else 0):>8.0f}")
