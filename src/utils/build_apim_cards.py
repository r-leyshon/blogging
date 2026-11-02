#!/usr/bin/env python3
"""Build the experiment data, cards and chart data for blog 24 (APIM load balancing).

Inputs
  * ../azure-load-balance-perf/experiment/results/*.json (k6 summaries; git-ignored upstream)
    If that folder is absent, the committed www/24-apim-load-balance-perf/runs.json is reused.
  * The RUNS table below: group, regime, quota, friendly name and description per run id.

Outputs
  * www/24-apim-load-balance-perf/runs.json     (the only committed copy of the data)
  * www/24-apim-load-balance-perf/scatter.html  (refreshes the embedded DATA)
  * blogs/includes/24-runs-*.html               (one card set per tab)

Run from anywhere:  python3 src/utils/build_apim_cards.py
"""
from __future__ import annotations

import html
import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WWW = ROOT / "www" / "24-apim-load-balance-perf"
INC = ROOT / "blogs" / "includes"
RESULTS = ROOT.parent / "azure-load-balance-perf" / "experiment" / "results"

# Measured sustained ceiling at 60,000 TPM: 3 regions x 72 requests a minute x 5 minutes.
SUSTAINED_CEILING = 3 * 72 * 5

# ---------------------------------------------------------------------------
# Run catalogue: run_id -> (group, regime, quota_tpm, friendly name, description)
# regime: burst | sustained | spill
# ---------------------------------------------------------------------------
B = "burst"
S = "sustained"
P = "spill"
K10, K60 = 10_000, 60_000

RUNS: dict[str, tuple[str, str, int, str, str]] = {
    # --- 200-request bursts at 10,000 TPM: no retry ---------------------------------
    "baseline": ("No retry", B, K10, "Control: even split, no policies",
                 "Equal weights across the three regions. No circuit breaker, no retry."),
    "weighted_primary": ("No retry", B, K10, "Weighted 60/25/15, nothing else",
                         "UK South takes 60% of the traffic, West Europe 25%, Sweden Central 15%. Still no breaker and no retry."),
    "circuit_breaker": ("No retry", B, K10, "Circuit breaker only",
                        "Equal weights. A region leaves the pool after three failures inside 60 seconds, and a 429 counts as a failure. "
                        "Nothing retries onto whoever is left."),
    "gateway_throttle": ("No retry", B, K10, "Gateway cap of 10 requests a minute",
                         "The gateway refuses calls beyond 10 a minute, before Foundry sees them."),
    "full_resilience": ("No retry", B, K10, "Weights, breaker and a 500-a-minute cap",
                        "Weights, a circuit breaker and a 500 requests-a-minute gateway cap, with no retry. "
                        "Every call was refused in about 12 ms, too fast to have reached the model."),
    "asymmetric_cb": ("No retry", B, K10, "Skewed 90/5/5 and breaker, no retry",
                      "90% of traffic lands on UK South, which runs out first and can trip the breaker. No retry."),
    "cb_5xx_only": ("No retry", B, K10, "Breaker on server errors only, no retry",
                    "The breaker ignores 429s and only trips on 5xx, so running out of quota never removes a region. No retry."),
    # --- direct ----------------------------------------------------------------------
    "direct_equal": ("Direct (no gateway)", B, K10, "Direct to Foundry, even split",
                     "No gateway. The client splits calls evenly across the three regions and does not fall back. "
                     "The matched pair for the control."),
    "direct_weighted": ("Direct (no gateway)", B, K10, "Direct, 60/25/15, no fallback",
                        "No gateway. The client picks a region at random (60/25/15) and does not fall back when that region is exhausted."),
    "direct_sequential": ("Direct (no gateway)", B, K10, "Direct, walk the regions in order",
                          "No gateway. The client tries UK South, then West Europe, then Sweden Central, moving on only after a failure. "
                          "It made 567 HTTP calls to land 33 successes."),
    # --- client retry ----------------------------------------------------------------
    "retry_immediate": ("Client retry", B, K10, "Client retry, immediately",
                        "The client retries a 429 straight away, up to three times, against an equal-weight pool with no breaker."),
    "retry_fixed_1s": ("Client retry", B, K10, "Client retry, fixed 1 s pause",
                       "The same client retry, with a fixed one second pause between attempts."),
    "retry_backoff": ("Client retry", B, K10, "Client retry, exponential backoff",
                      "Client retry with exponential backoff: 500 ms, then 1 s, then 2 s."),
    "retry_backoff_jitter": ("Client retry", B, K10, "Client retry, backoff with jitter",
                             "Backoff plus jitter, so the virtual users do not all wake up on the same tick."),
    "retry_after_header": ("Client retry", B, K10, "Client retry, wait for Retry-After",
                           "The client sleeps for the Retry-After value Azure returns, usually the rest of the quota window."),
    "optimal_equal_client": ("Client retry", B, K10, "Client retry, wait for Retry-After (repeat)",
                             "A repeat of the same setup, run again under another name."),
    # --- pool retry ------------------------------------------------------------------
    "apim_retry_equal": ("Pool retry", B, K10, "Pool retry, even split, no breaker",
                         "Equal weights. The gateway retries the pool up to three times. With no breaker, the pool never shrinks."),
    "optimal_equal_apim": ("Pool retry", B, K10, "Pool retry, even split, no breaker (repeat)",
                           "A repeat of the same configuration, run again under another name."),
    "apim_retry_cb": ("Pool retry", B, K10, "Pool retry and breaker (429 + 5xx), even split",
                      "Equal weights, breaker on 429 and 5xx, and the gateway retries whichever regions are still in the pool."),
    "apim_retry_asym": ("Pool retry", B, K10, "Pool retry and breaker (429 + 5xx), 90/5/5",
                        "Skewed weights, breaker on 429 and 5xx, pool retry. UK South is expected to trip first."),
    "optimal_asym_apim": ("Pool retry", B, K10, "Pool retry and breaker (429 + 5xx), 90/5/5 (repeat)",
                          "A repeat of the identical configuration, run again under another name. The two results differ."),
    "asym_retry_no_cb": ("Pool retry", B, K10, "Pool retry, 90/5/5, no breaker",
                         "Skewed weights and pool retry with the breaker off."),
    "asym_retry_cb_5xx": ("Pool retry", B, K10, "Pool retry and breaker (5xx only), 90/5/5",
                          "Skewed weights, breaker on 5xx only, pool retry. Running out of quota never trips the breaker."),
    "weight_70_15_15": ("Pool retry", B, K10, "Pool retry and breaker, 70/15/15",
                        "A gentler skew than 90/5/5, with the breaker on 429 and 5xx and pool retry."),
    "weight_80_10_10": ("Pool retry", B, K10, "Pool retry and breaker, 80/10/10",
                        "An in-between skew: the spare regions get 10% each, with breaker on 429 and 5xx and pool retry."),
    "trip_count_1": ("Pool retry", B, K10, "Pool retry, breaker trips on first failure",
                     "90/5/5 weights and pool retry, with the breaker tripping on the first failure instead of the third."),
    # --- stacked ---------------------------------------------------------------------
    "optimal_asym_client": ("Stacked retries", B, K10, "Breaker plus client Retry-After, no pool retry",
                            "Skewed weights and breaker on 429 and 5xx, with the client sleeping for Retry-After instead of the gateway retrying."),
    "optimal_combined": ("Stacked retries", B, K10, "Pool retry, breaker and client Retry-After, 90/5/5",
                         "The gateway setup from the pool-retry group with a client Retry-After sleep as a backstop. "
                         "The run ended in about 2.5 seconds, so the client sleep never fired."),
    # --- quota to spare (60K burst) --------------------------------------------------
    "apim_retry_equal_r2": ("Quota to spare", B, K60, "Pool retry, even split, no breaker",
                            "The pool-retry setup from the 10,000 TPM group, with six times the quota. "
                            "200 requests fit inside one minute's quota."),
    "optimal_equal_apim_r2": ("Quota to spare", B, K60, "Pool retry, even split, no breaker (repeat)",
                              "The same configuration again, run on its own later."),
    "asym_retry_no_cb_r2": ("Quota to spare", B, K60, "Pool retry, 90/5/5, no breaker",
                            "Skewed weights and pool retry with the breaker off, at 60,000 TPM."),
    # --- sustained 60K ---------------------------------------------------------------
    "sustained_baseline_r2": ("5-minute runs", S, K60, "Control: even split, no policies",
                              "Five minutes of equal weights, no breaker, no retry."),
    "sustained_apim_retry_60k": ("5-minute runs", S, K60, "Pool retry, even split, no breaker",
                                 "Five minutes of equal weights, no breaker, and pool retry."),
    "sustained_cb_only_r2": ("5-minute runs", S, K60, "Breaker only, even split",
                             "Five minutes of equal weights and a breaker on 429 and 5xx, with no retry."),
    "sustained_apim_asym_60k": ("5-minute runs", S, K60, "Pool retry and breaker (429 + 5xx), 90/5/5",
                                "Five minutes of 90/5/5 weights, a breaker on 429 and 5xx, and pool retry."),
    # --- one region saturated (raw runs, aggregated into arms below) -----------------
    "car_baseline": ("Primary region short", P, K60, "calibration", ""),
    "car_90_5_5": ("Primary region short", P, K60, "no_recovery", ""),
    "car_90_5_5_r2": ("Primary region short", P, K60, "no_recovery", ""),
    "car_90_5_5_r3": ("Primary region short", P, K60, "no_recovery", ""),
    "car_cb5xx_90_5_5": ("Primary region short", P, K60, "cb5xx", ""),
    "car_retry_90_5_5": ("Primary region short", P, K60, "retry_only", ""),
    "car_retry_90_5_5_r2": ("Primary region short", P, K60, "retry_only", ""),
    "car_retry_90_5_5_r3": ("Primary region short", P, K60, "retry_only", ""),
    "car_retry_cb5xx_90_5_5": ("Primary region short", P, K60, "retry_cb5xx", ""),
    "car_retry_cb429_90_5_5": ("Primary region short", P, K60, "retry_cb429", ""),
    "car_retry_cb429_90_5_5_r2": ("Primary region short", P, K60, "retry_cb429", ""),
    "car_retry_cb429_90_5_5_r3": ("Primary region short", P, K60, "retry_cb429", ""),
    "car_retry_cb429_90_5_5_trip1": ("Primary region short", P, K60, "retry_cb429_trip1", ""),
    "car_direct_spill": ("Primary region short", P, K60, "direct", ""),
    "car_direct_spill_r2": ("Primary region short", P, K60, "direct", ""),
    "car_direct_spill_r3": ("Primary region short", P, K60, "direct", ""),
}

# Arms of the one-region-saturated experiment (2 requests a second, 90/5/5 unless stated).
ARMS: dict[str, tuple[str, str]] = {
    "calibration": ("Calibration: even split at 1 request a second",
                    "Equal weights at half the rate used for the other runs, with nothing wrong with any region. "
                    "If this does not reach about 100%, the rate is too high for the test to mean anything."),
    "no_recovery": ("No recovery: 90/5/5, nothing else",
                    "UK South is offered about 108 requests a minute against a ceiling near 72. "
                    "The other two regions are nearly idle."),
    "cb5xx": ("Breaker on server errors only",
              "The breaker ignores 429s, so running out of quota never trips it. No retry."),
    "retry_only": ("Pool retry, no breaker",
                   "The gateway retries a 429 up to three times against the pool. Nothing is ever taken out of the pool."),
    "retry_cb5xx": ("Pool retry, breaker on server errors only",
                    "Pool retry with a breaker that never fires under quota errors."),
    "retry_cb429": ("Pool retry and breaker on 429, trips after three failures",
                    "UK South trips after three 429s and leaves the pool for 60 seconds, so retries can only reach the other two regions."),
    "retry_cb429_trip1": ("Pool retry and breaker on 429, trips after one failure",
                          "The same as the three-failure setup, but UK South leaves the pool after its first 429."),
    "direct": ("Direct: try UK South, then the next region",
               "No gateway. The client sends every call to UK South first and moves on after a 429. "
               "It needs credentials for all three regions."),
}

# Tabs: (group name, slug, colour, note)
TABS = [
    ("No retry", "none", "#1f7a8c",
     "200-request bursts, 10,000 TPM per region. With no retry, nothing gets past about 17%. "
     "A breaker or a request cap on its own makes it worse, and the busiest run completes nothing."),
    ("Direct (no gateway)", "direct", "#5c6b73",
     "200-request bursts, 10,000 TPM per region. Calling Foundry directly gives the same result as the gateway with no policies. "
     "Walking the regions in order only burns calls."),
    ("Client retry", "client", "#e09f3e",
     "200-request bursts, 10,000 TPM per region. Short pauses do nothing useful. "
     "Only sleeping for the full Retry-After works, and it costs about 30 seconds a call."),
    ("Pool retry", "pool", "#2a9d8f",
     "200-request bursts, 10,000 TPM per region. Retrying inside the gateway lands at the same 16-18% plateau as everything else, "
     "except where a breaker empties the pool. Identical configurations differ between runs."),
    ("Stacked retries", "stacked", "#bc4749",
     "200-request bursts, 10,000 TPM per region. A client Retry-After behind a breaker, with and without pool retry."),
    ("Quota to spare", "spare", "#8e7dbe",
     "200-request bursts, 60,000 TPM per region: six times the quota, so 200 requests fit inside one minute's allowance. "
     "The control from the 10,000 TPM runs is pinned for contrast."),
    ("5-minute runs", "sustained", "#264653",
     "Five minutes of continuous load at 60,000 TPM per region. The quota ceiling is about 1,080 completions. "
     "Ranked by completions, because success rate here mostly measures how fast the failures came back."),
    ("Primary region short", "spill", "#9c6644",
     "Constant 2 requests a second for five minutes at 60,000 TPM, with 90% of traffic aimed at UK South. "
     "Where a setup was repeated the card shows the mean of the runs and every individual result."),
]

REFERENCE = {  # tab group -> pinned item id and tag
    "default": ("baseline", "Reference, 10,000 TPM"),
    "5-minute runs": ("sustained_baseline_r2", "Reference"),
    "Primary region short": ("no_recovery", "Reference"),
}


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
def summarise(run_id: str) -> dict:
    j = json.loads((RESULTS / f"{run_id}.json").read_text())
    m = j["metrics"]
    dur = j["state"]["testRunDurationMs"] / 1000
    iters = int(m["iterations"]["values"]["count"])
    checks = {c["name"]: c for c in j["root_group"].get("checks", [])}
    if "eventual_successes" in m:
        succ = int(m["eventual_successes"]["values"]["count"])
    else:
        succ = int(checks["http 200 ok"]["passes"])
    calls = m.get("total_http_calls", {}).get("values", {}).get("count")
    if calls is None and run_id == "direct_sequential":
        calls = int(m["http_reqs"]["values"]["count"])
    p50_all = m["http_req_duration"]["values"]["med"] if "med" in m["http_req_duration"]["values"] else m["http_req_duration"]["values"]["p(50)"]
    ok = m.get("http_req_duration{expected_response:true}", {}).get("values", {})
    p50_ok = ok.get("med", ok.get("p(50)"))
    tts = m.get("time_to_success", {}).get("values", {})
    tts50 = tts.get("med", tts.get("p(50)"))
    return {
        "iterations": iters,
        "successes": succ,
        "success_rate_pct": round(succ / iters * 100, 3),
        "duration_s": round(dur, 2),
        "throughput_rps": round(iters / dur, 3),
        "goodput_rps": round(succ / dur, 3),
        "calls": int(calls) if calls is not None else None,
        "p50_ms": round(p50_all, 1),
        "p50_success_ms": round(p50_ok, 1) if p50_ok is not None else None,
        "tts_p50_ms": round(tts50, 1) if tts50 is not None else None,
        "fast_refusals": bool(p50_all < 20),
    }


def ingest(path: Path) -> dict:
    old = json.loads(path.read_text()) if path.exists() else {}
    runs = []
    for run_id, (group, regime, quota, label, description) in RUNS.items():
        rec = {"run_id": run_id, "group": group, "regime": regime, "quota_tpm": quota}
        rec.update(summarise(run_id))
        if regime != P:
            rec["label"], rec["description"] = label, description
        else:
            rec["arm"] = label
        runs.append(rec)
    return {
        "metrics": {
            "success_rate": "Eventual HTTP 200s with a valid body / original requests x 100",
            "throughput": "Original requests / wall-clock seconds",
            "goodput": "Successful completions / wall-clock seconds (= throughput x success rate)",
        },
        "source": old.get("source", "https://github.com/r-leyshon/azure-load-balance-perf"),
        "sustained_ceiling_completions": SUSTAINED_CEILING,
        "runs": runs,
    }


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------
def fmt_rate(x: float) -> str:
    if x >= 100:
        return f"{x:.0f}"
    if x >= 10:
        return f"{x:.1f}"
    return f"{x:.2f}"


def fmt_quota(q: int) -> str:
    return f"{q:,} TPM"


def bar(label: str, pct: float, value: str) -> str:
    shown = max(pct, 0.5)
    return (
        f'<div class="mbar"><span class="k">{label}</span>'
        f'<span class="track"><i style="--pct:{min(shown, 100):.1f}"></i></span>'
        f'<span class="v">{value}</span></div>'
    )


def card(title: str, ident: str, description: str, bars: list[str], meta: list[str],
         colour: str, tag: str = "", fast: bool = False) -> str:
    cls = "exp-card exp-ref" if tag else "exp-card"
    tag_html = f'<span class="ref-tag">{html.escape(tag)}</span>' if tag else ""
    fast_html = '<span class="ref-tag fast-tag">Fast refusals</span>' if fast else ""
    meta_html = "".join(f'<p class="meta">{m}</p>' for m in meta)
    return "\n".join(
        [
            f'<article class="{cls}" style="--edge:{colour}">',
            f'<h4>{html.escape(title)}{tag_html}{fast_html}</h4>',
            f'<code class="run-id">{ident}</code>',
            f'<p>{html.escape(description)}</p>',
            *bars,
            meta_html,
            "</article>",
        ]
    )


def burst_card(r: dict, maxima: dict, colour: str, tag: str = "") -> str:
    meta = [
        f'Completed <b>{r["successes"]}</b> of {r["iterations"]} requests in {r["duration_s"]:.1f} s '
        f'&middot; {fmt_quota(r["quota_tpm"])} per region'
    ]
    bars = [
        bar("Success", r["success_rate_pct"], f'{r["success_rate_pct"]:.1f}%'),
        bar("Throughput", r["throughput_rps"] / maxima["throughput"] * 100, f'{fmt_rate(r["throughput_rps"])}/s'),
        bar("Goodput", r["goodput_rps"] / maxima["goodput"] * 100, f'{fmt_rate(r["goodput_rps"])}/s'),
    ]
    return card(r["label"], r["run_id"], r["description"], bars, meta, colour, tag, r["fast_refusals"])


def sustained_card(r: dict, ceiling: int, colour: str, tag: str = "") -> str:
    of_ceiling = r["successes"] / ceiling * 100
    meta = [
        f'<b>{r["successes"]:,}</b> completions in {r["duration_s"]:.0f} s from {r["iterations"]:,} requests tried '
        f'&middot; median call {r["p50_ms"]:.0f} ms'
    ]
    bars = [
        bar("Of ceiling", of_ceiling, f"{of_ceiling:.1f}%"),
        bar("Goodput", r["goodput_rps"] / (ceiling / 300) * 100, f'{r["goodput_rps"]:.2f}/s'),
    ]
    return card(r["label"], r["run_id"], r["description"], bars, meta, colour, tag, r["fast_refusals"])


def arm_summary(arm_id: str, runs: list[dict]) -> dict:
    mine = sorted((r for r in runs if r["arm"] == arm_id), key=lambda r: r["run_id"])
    rates = [r["success_rate_pct"] for r in mine]
    calls = [r["calls"] / r["iterations"] for r in mine if r["calls"]]
    ok = [r["p50_success_ms"] for r in mine if r["p50_success_ms"]]
    return {
        "arm_id": arm_id,
        "run_ids": [r["run_id"] for r in mine],
        "rates": rates,
        "mean": statistics.mean(rates),
        "n": len(mine),
        "calls_per_request": (min(calls), max(calls)) if calls else None,
        "p50_success_ms": statistics.mean(ok),
    }


def arm_card(s: dict, colour: str, tag: str = "") -> str:
    title, description = ARMS[s["arm_id"]]
    rates = ", ".join(f"{x:.1f}%" for x in s["rates"])
    meta = [f'{str(s["n"]) + " runs" if s["n"] > 1 else "One run"}: {rates}',
            f'Median successful call {s["p50_success_ms"]:.0f} ms']
    if s["calls_per_request"] and s["arm_id"] == "direct":
        lo, hi = s["calls_per_request"]
        meta.append(f"{lo - 1:.2f} to {hi - 1:.2f} extra calls per request, because the first try at UK South is refused")
    bars = [bar("Success", s["mean"], f'{s["mean"]:.1f}%')]
    ids = ", ".join(s["run_ids"])
    return card(title, ids, description, bars, meta, colour, tag)


def grid(note: str, cards: list[str]) -> str:
    return f'<p class="tab-note">{html.escape(note)}</p>\n<div class="exp-grid">\n' + "\n".join(cards) + "\n</div>\n"


def sort_key(r: dict):
    return (-r["success_rate_pct"], -r["successes"], -r["goodput_rps"])


def main() -> None:
    path = WWW / "runs.json"
    if RESULTS.exists():
        data = ingest(path)
    else:
        data = json.loads(path.read_text())
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n")

    runs = data["runs"]
    by_id = {r["run_id"]: r for r in runs}
    colours = {name: colour for name, _, colour, _ in TABS}

    burst = [r for r in runs if r["regime"] == B]
    maxima = {
        "throughput": max(r["throughput_rps"] for r in burst),
        "goodput": max(r["goodput_rps"] for r in burst),
    }
    arms = {a: arm_summary(a, [r for r in runs if r["regime"] == P]) for a in ARMS}

    for name, slug, colour, note in TABS:
        members = [r for r in runs if r["group"] == name]
        pin_id, pin_tag = REFERENCE.get(name, REFERENCE["default"])
        cards: list[str] = []
        if name == "Primary region short":
            ordered = sorted(arms.values(), key=lambda s: -s["mean"])
            cards.append(arm_card(arms[pin_id], colour, pin_tag))
            cards += [arm_card(s, colour) for s in ordered if s["arm_id"] != pin_id]
        elif name == "5-minute runs":
            ordered = sorted(members, key=lambda r: -r["successes"])
            cards.append(sustained_card(by_id[pin_id], SUSTAINED_CEILING, colour, pin_tag))
            cards += [sustained_card(r, SUSTAINED_CEILING, colour) for r in ordered if r["run_id"] != pin_id]
        else:
            ordered = sorted(members, key=sort_key)
            in_group = any(r["run_id"] == pin_id for r in members)
            cards.append(burst_card(by_id[pin_id], maxima, colours[by_id[pin_id]["group"]], pin_tag))
            cards += [burst_card(r, maxima, colour) for r in ordered if not (in_group and r["run_id"] == pin_id)]
        (INC / f"24-runs-{slug}.html").write_text(grid(note, cards))

    # Remove include files from the previous design.
    stale = INC / "24-runs-all.html"
    if stale.exists():
        stale.unlink()

    # Chart data: bursts only (sustained and arrival-rate runs are not comparable on goodput).
    chart = {**{k: v for k, v in data.items() if k != "runs"}, "runs": [
        {k: r[k] for k in ("run_id", "group", "quota_tpm", "iterations", "successes", "success_rate_pct",
                           "duration_s", "throughput_rps", "goodput_rps", "label", "description", "fast_refusals")}
        for r in sorted(burst, key=lambda r: -r["success_rate_pct"])
    ]}
    scatter = WWW / "scatter.html"
    text = scatter.read_text()
    new_text, n = re.subn(
        r"const DATA = \{.*?\n\};",
        lambda _: "const DATA = " + json.dumps(chart, indent=2, ensure_ascii=True) + ";",
        text,
        count=1,
        flags=re.S,
    )
    if n != 1:
        raise SystemExit("could not find the DATA block in scatter.html")
    scatter.write_text(new_text)

    for s in sorted(arms.values(), key=lambda s: -s["mean"]):
        print(f'arm {s["arm_id"]:18s} mean {s["mean"]:.1f}  {s["rates"]}')
    print(f"{len(runs)} runs ({len(burst)} burst); wrote runs.json, scatter.html and {len(TABS)} include files")


if __name__ == "__main__":
    main()
