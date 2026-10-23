#!/usr/bin/env python3
"""Reproducible open-loop load against an operator-provided Telegram bridge.

The target is a POST endpoint accepting {request_id, mode, query}. Its response
must be JSON {request_id: <same id>, telegram_e2e_completed: true} emitted only
after the bot's Telegram reply arrives. A webhook acknowledgement or Bot API
sendMessage acknowledgement alone cannot prove an end-to-end measurement and
is counted as failure. The frozen app provides no such HTTP query endpoint;
an external bridge is an environment prerequisite, never supplied by this tool.
No application imports, credentials discovery, or network calls in --dry-run.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import sys
import time
import urllib.error
import urllib.request


SCENARIOS = (
    ("vpn", "it_support", "Как подключить VPN?"),
    ("mail", "it_support", "Как настроить корпоративную почту?"),
    ("git", "it_support", "Как получить Git-доступ?"),
    ("insurance", "benefits", "Как подключить ДМС?"),
    ("vacation", "benefits", "Как оформить отпуск?"),
    ("sick_leave", "benefits", "Как оформить больничный?"),
    ("courses", "learning", "Где находится каталог курсов?"),
    ("approval", "learning", "Как согласовать обучение?"),
    ("budget", "learning", "Какой бюджет на обучение?"),
    ("schedule", "culture", "Какой график работы?"),
    ("dress_code", "culture", "Какой дресс-код?"),
    ("business_trip", "culture", "Как оформить командировку?"),
)
RAG_UNAVAILABLE = (
    "rag-only requires /debug/rag_latency endpoint, which is not "
    "exposed by the frozen application. AC-N02 remains "
    "pending_environment pending a separate small PR or an "
    "out-of-band profiling run."
)


def percentile95(values: list[float]) -> float:
    """User-specified zero-based index: sorted[950] for 1000 samples."""
    if not values:
        raise ValueError("p95 requires samples")
    return sorted(values)[min(math.floor(len(values) * 0.95), len(values) - 1)]


def build_manifest(offered: int, samples: int, seed: int) -> list[dict]:
    """Sample offered request IDs independently per cyclic scenario stratum."""
    rng = random.Random(seed)
    base, extra = divmod(samples, len(SCENARIOS))
    result = []
    for scenario_index, (scenario, mode, query) in enumerate(SCENARIOS):
        population = range(scenario_index, offered, len(SCENARIOS))
        count = base + (scenario_index < extra)
        if count > len(population):
            raise ValueError("insufficient offered requests for stratified sample")
        for request_id in rng.sample(population, count):
            result.append({"request_id": request_id, "scenario": scenario,
                           "mode": mode, "query": query})
    return sorted(result, key=lambda row: row["request_id"])


def post_query(target_url: str, request_id: int, mode: str, query: str,
               scheduled_at: float | None = None) -> float:
    """Measure completed bridge round trip; any error contributes +infinity."""
    payload = json.dumps({"request_id": request_id, "mode": mode,
                          "query": query}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(target_url, data=payload, method="POST",
                                     headers={"Content-Type": "application/json"})
    started = time.monotonic() if scheduled_at is None else scheduled_at
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read(1024 * 1024).decode("utf-8"))
            if not 200 <= response.status < 300:
                return math.inf
        if (not isinstance(result, dict)
                or result.get("telegram_e2e_completed") is not True
                or result.get("request_id") != request_id):
            return math.inf
        return (time.monotonic() - started) * 1000
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return math.inf


def run_offered(args, offered: int, selected: set[int]) -> dict[int, float]:
    """Offer every cyclic request at the declared rate, including unsampled ones."""
    measurements = {}
    # Allow all timeout-bound requests to remain in flight at the offered rate.
    # Timing includes scheduler/worker delay, preventing coordinated omission.
    with ThreadPoolExecutor(max_workers=math.ceil(args.rps * 30) + 1) as pool:
        for warmup_id in range(args.warmup):
            _, mode, query = SCENARIOS[warmup_id % len(SCENARIOS)]
            # Warmup requests are deliberately outside the measured ID range.
            post_query(args.target_url, -warmup_id - 1, mode, query)
        start = time.monotonic()
        futures = {}
        for request_id in range(offered):
            scheduled_at = start + request_id / args.rps
            delay = scheduled_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            _, mode, query = SCENARIOS[request_id % len(SCENARIOS)]
            future = pool.submit(post_query, args.target_url, request_id, mode, query,
                                 scheduled_at)
            futures[future] = request_id
        for future in as_completed(futures):
            request_id = futures[future]
            if request_id in selected:
                try:
                    measurements[request_id] = future.result()
                except Exception:
                    measurements[request_id] = math.inf
    return measurements


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-url")
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--rps", type=float, default=10)
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("artifacts"))
    parser.add_argument("--dry-run", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--telegram-e2e", "--telegram-only", action="store_true", default=True)
    mode.add_argument("--rag-only", action="store_true")
    args = parser.parse_args(argv)
    if args.rag_only:
        print(RAG_UNAVAILABLE, file=sys.stderr)
        return 2
    if (not math.isfinite(args.rps) or args.rps <= 0 or args.duration <= 0
            or args.samples <= 0 or args.warmup < 0):
        parser.error("rps/duration/samples must be positive; warmup must be nonnegative")
    offered = math.floor(args.rps * args.duration)
    try:
        manifest = build_manifest(offered, args.samples, args.seed)
    except ValueError as error:
        parser.error(str(error))
    if not args.dry_run and (not args.target_url or not args.target_url.startswith(("http://", "https://"))):
        parser.error("--target-url must identify an external HTTP(S) Telegram round-trip bridge")
    args.out.mkdir(parents=True, exist_ok=True)
    plan = {"seed": args.seed, "expected_rps": args.rps,
            "expected_duration": args.duration, "offered_request_count": offered,
            "expected_request_count": offered + args.warmup,
            "warmup_request_count": args.warmup,
            "sample_count": len(manifest),
            "stratification": dict(Counter(row["scenario"] for row in manifest)),
            "thresholds": {"p95_telegram_e2e_ms": 3000, "p95_rag_only_ms": 200},
            "sample_manifest": manifest}
    # Persist before warmup or any measured request; identical inputs give identical JSON.
    (args.out / "sample_manifest.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False))
        return 0
    print("warning: RAG-only latency unavailable; no /debug/rag_latency endpoint", file=sys.stderr)
    measurements = run_offered(args, offered, {row["request_id"] for row in manifest})
    values = [measurements.get(row["request_id"], math.inf) for row in manifest]
    p95 = percentile95(values)
    # Standard JSON cannot represent infinity: encode it explicitly, never as zero.
    summary = {"timestamp": datetime.now(timezone.utc).isoformat(),
               "sample_count": len(values), "failed_samples": sum(math.isinf(v) for v in values),
               "p95_telegram_e2e_ms": p95 if math.isfinite(p95) else "+inf",
               "rag_only_ms": None, "rag_only_status": "pending_environment",
               "threshold_met": p95 <= 3000,
               "samples": [{"request_id": row["request_id"],
                            "telegram_e2e_ms": value if math.isfinite(value) else "+inf"}
                           for row, value in zip(manifest, values)]}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "samples"}))
    return 0 if p95 <= 3000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
