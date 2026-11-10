#!/usr/bin/env python3
"""Build the experiment data, cards and chart data for blog 24 (APIM load balancing).

Inputs
  * ../azure-load-balance-perf/experiment/results/*.json (k6 summaries; git-ignored upstream)
    If that folder is absent, the committed www/24-apim-load-balance-perf/runs.json is reused.
  * The RUNS table (200-request bursts) and the MATCHED table (steady-rate matched pairs of
    gateway and client) below: tab, friendly name and description per run or arm.

Outputs
  * www/24-apim-load-balance-perf/runs.json     (the only committed copy of the data)
  * www/24-apim-load-balance-perf/scatter.html  (refreshes the embedded DATA: bursts, steady runs,
                                                  region speed; page shows one view via ?view=)
  * blogs/includes/24-runs-*.html               (one card set per tab)

Validity rule for the matched pairs (set in the experiment repo before the runs): a run is
discarded if k6 ran for more than 330 s (the laptop slept) or dropped iterations.

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

MAX_VALID_SECONDS = 330

# ---------------------------------------------------------------------------
# 200-request bursts: run_id -> (tab, regime, quota_tpm, friendly name, description)
#
# Bug note: in the burst runs whose tab is "Breaker and weights" or "Quota to spare" a gateway
# retry rule was configured, but a bug (the request body was lost on the second attempt) meant
# it never reached the model. They are valid runs of what actually ran: a breaker and weights,
# with no working retry. Names and descriptions say so.
# ---------------------------------------------------------------------------
B = "burst"
K10, K60 = 10_000, 60_000

RUNS: dict[str, tuple[str, str, int, str, str]] = {
    # --- no retry ---------------------------------------------------------------------
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
    "optimal_asym_client": ("Client retry", B, K10, "Breaker plus client Retry-After",
                            "Skewed 90/5/5 weights and a breaker on 429 and 5xx, with the client sleeping for Retry-After."),
    # --- breaker and weights (a gateway retry rule was set but never worked) ----------
    "apim_retry_equal": ("Breaker and weights", B, K10, "Even split, no breaker",
                         "Equal weights and no breaker. A gateway retry rule was set but never worked, so this is the control again."),
    "optimal_equal_apim": ("Breaker and weights", B, K10, "Even split, no breaker (repeat)",
                           "A repeat of the same configuration, run again under another name."),
    "apim_retry_cb": ("Breaker and weights", B, K10, "Breaker on 429 and 5xx, even split (repeat)",
                      "Equal weights and a breaker on 429 and 5xx: the same as the breaker-only run, run again. "
                      "The gateway retry rule set here never worked."),
    "apim_retry_asym": ("Breaker and weights", B, K10, "Breaker on 429 and 5xx, 90/5/5",
                        "Skewed weights and a breaker on 429 and 5xx. UK South is expected to trip first."),
    "optimal_asym_apim": ("Breaker and weights", B, K10, "Breaker on 429 and 5xx, 90/5/5 (repeat)",
                          "A repeat of the identical configuration, run again under another name. The two results differ."),
    "asym_retry_no_cb": ("Breaker and weights", B, K10, "Skewed 90/5/5, no breaker",
                         "Skewed weights with the breaker off."),
    "asym_retry_cb_5xx": ("Breaker and weights", B, K10, "Breaker on 5xx only, 90/5/5",
                          "Skewed weights, breaker on 5xx only. Running out of quota never trips the breaker."),
    "weight_70_15_15": ("Breaker and weights", B, K10, "Breaker, 70/15/15",
                        "A gentler skew than 90/5/5, with the breaker on 429 and 5xx."),
    "weight_80_10_10": ("Breaker and weights", B, K10, "Breaker, 80/10/10",
                        "An in-between skew: the spare regions get 10% each, with the breaker on 429 and 5xx."),
    "trip_count_1": ("Breaker and weights", B, K10, "Breaker trips on first failure, 90/5/5",
                     "90/5/5 weights, with the breaker tripping on the first failure instead of the third."),
    # --- quota to spare (60K burst) --------------------------------------------------
    "apim_retry_equal_r2": ("Quota to spare", B, K60, "Even split, no breaker",
                            "The even-split control with six times the quota. 200 requests fit inside one minute's quota. "
                            "A gateway retry rule was set but never worked."),
    "optimal_equal_apim_r2": ("Quota to spare", B, K60, "Even split, no breaker (repeat)",
                              "The same configuration again, run on its own later."),
    "asym_retry_no_cb_r2": ("Quota to spare", B, K60, "Skewed 90/5/5, no breaker",
                            "Skewed weights with the breaker off, at 60,000 TPM."),
}

# ---------------------------------------------------------------------------
# Matched pairs at a steady rate (60,000 TPM per region, five minutes per run).
# Each arm: id -> dict(tab, side, title, desc, stems | explicit)
#   stems:    run ids look like <stem>_r1, <stem>_r2 ...
#   explicit: complete run ids
# side: "gateway" (tab colour edge) or "client" (grey edge, no gateway)
# ---------------------------------------------------------------------------
GREY = "#5c6b73"
PRIMARY, FALLBACKS, EVERYWHERE, HEALTHY = ("Primary region short", "Fallbacks busy",
                                           "Every region short (steady)", "Nothing wrong")

MATCHED: dict[str, dict] = {
    # ---- Primary region short: 2 requests a second, 90/5/5 -----------------------------
    "a_reference": dict(tab=PRIMARY, side="gateway", explicit=["car_90_5_5", "car_90_5_5_r2", "car_90_5_5_r3"],
        title="Gateway: 90/5/5, nothing else",
        desc="No breaker and no retry. UK South is offered about 108 requests a minute against a ceiling near 72, "
             "and the other two regions are nearly idle."),
    "a_gw_cb5xx": dict(tab=PRIMARY, side="gateway", explicit=["car_cb5xx_90_5_5"],
        title="Gateway: breaker on server errors only",
        desc="The breaker ignores 429s, so running out of quota never removes UK South. No retry."),
    "a_gw_retry": dict(tab=PRIMARY, side="gateway", stems=["p6a_apim_retry_no_cb"],
        title="Gateway: retry only, no breaker",
        desc="The gateway retries a refused call up to twice more, waiting one second each time. "
             "Nothing is remembered, so each retry picks a region by weight again."),
    "a_gw_retry0": dict(tab=PRIMARY, side="gateway", stems=["p6a_apim_retry_no_cb_int0"],
        title="Gateway: retry only, no waiting",
        desc="The same, with no pause between attempts."),
    "a_gw_cb3": dict(tab=PRIMARY, side="gateway", stems=["p6a_apim_retry_cb"],
        title="Gateway: retry and breaker (trips after 3 failures)",
        desc="UK South leaves the pool for 60 seconds after three refusals, so retries can only reach the other two regions."),
    "a_gw_cb1": dict(tab=PRIMARY, side="gateway", stems=["p6a_apim_retry_cb_trip1"],
        title="Gateway: retry and breaker (trips after 1 failure)",
        desc="The same, but UK South leaves the pool after its first refusal."),
    "a_gw_priority": dict(tab=PRIMARY, side="gateway", stems=["p6a_apim_priority"],
        title="Gateway: priority list",
        desc="UK South is first choice and the others are used only when it is out of the pool. Breaker trips after one failure."),
    "a_cl_weighted": dict(tab=PRIMARY, side="client", stems=["p5a_direct_weighted", "p6a_direct_weighted"],
        title="Client: 90/5/5, retry, no memory",
        desc="No gateway. The client picks a region by weight and retries up to twice more, picking again each time."),
    "a_cl_weighted_mem": dict(tab=PRIMARY, side="client", stems=["p5a_direct_weighted_mem", "p6a_direct_weighted_mem"],
        title="Client: 90/5/5, retry, 60 s cool-down",
        desc="As above, but after a refusal that caller skips that region for 60 seconds."),
    "a_cl_seq_mem": dict(tab=PRIMARY, side="client", stems=["p5a_direct_seq_mem", "p6a_direct_seq_mem"],
        title="Client: UK South first, 60 s cool-down",
        desc="The client tries UK South, then the next region, and skips a region for 60 seconds after a refusal."),
    "a_cl_seq": dict(tab=PRIMARY, side="client", stems=["p5a_direct_seq"],
        title="Client: UK South first, no memory",
        desc="The client tries UK South, then the next region, with nothing remembered between requests."),
    # ---- Fallbacks busy: 3 requests a second -------------------------------------------
    "b_gw_cb3": dict(tab=FALLBACKS, side="gateway", stems=["p6b_apim_retry_cb"],
        title="Gateway: retry and breaker (trips after 3 failures)",
        desc="UK South leaves the pool for 60 seconds after three refusals."),
    "b_gw_cb1": dict(tab=FALLBACKS, side="gateway", stems=["p6b_apim_retry_cb_trip1"],
        title="Gateway: retry and breaker (trips after 1 failure)",
        desc="UK South leaves the pool after its first refusal."),
    "b_gw_priority": dict(tab=FALLBACKS, side="gateway", stems=["p6b_apim_priority"],
        title="Gateway: priority list",
        desc="UK South first, the others only when it is out of the pool. Breaker trips after one failure."),
    "b_cl_seq": dict(tab=FALLBACKS, side="client", stems=["p5b_direct_seq"],
        title="Client: UK South first, no memory",
        desc="No gateway. Every request tries UK South first and moves on after a refusal."),
    "b_cl_seq_mem": dict(tab=FALLBACKS, side="client", stems=["p5b_direct_seq_mem"],
        title="Client: UK South first, 60 s cool-down",
        desc="As above, but a region that refused is skipped for 60 seconds."),
    "b_cl_weighted_mem": dict(tab=FALLBACKS, side="client", stems=["p5b_direct_weighted_mem"],
        title="Client: 90/5/5, retry, 60 s cool-down",
        desc="The client picks a region by weight, retries, and skips a region for 60 seconds after a refusal."),
    # ---- Every region short: 6 requests a second ---------------------------------------
    "d_gw_priority": dict(tab=EVERYWHERE, side="gateway", stems=["p6d_apim_priority"],
        title="Gateway: priority list",
        desc="UK South first, the others only when it is out of the pool. Breaker trips after one failure."),
    "d_gw_cb1": dict(tab=EVERYWHERE, side="gateway", stems=["p6d_apim_retry_cb_trip1_eq"],
        title="Gateway: retry and breaker (trips after 1 failure), even split",
        desc="Equal weights, retry, and a breaker that trips after one failure."),
    "d_cl_seq_mem": dict(tab=EVERYWHERE, side="client", stems=["p5d_direct_seq_mem"],
        title="Client: UK South first, 60 s cool-down",
        desc="No gateway. The client tries UK South, then the next region, and skips a region for 60 seconds after a refusal."),
    "d_cl_weighted_mem": dict(tab=EVERYWHERE, side="client", stems=["p5d_direct_weighted_mem_eq"],
        title="Client: even split, retry, 60 s cool-down",
        desc="The client picks a region at random, retries, and skips a region for 60 seconds after a refusal."),
    # ---- Nothing wrong: 1 request a second ---------------------------------------------
    "c_cl": dict(tab=HEALTHY, side="client", stems=["p5c_direct_equal"],
        title="Client: even split",
        desc="No gateway and no failures: the client splits calls evenly across the three regions."),
    "c_gw": dict(tab=HEALTHY, side="gateway", stems=["p5c_apim_baseline"],
        title="Gateway: even split",
        desc="The same traffic through the gateway with equal weights and no breaker. Nothing is refused, so no recovery is needed."),
}

# Which arm is pinned as the reference card in each matched tab (None = no pin).
MATCHED_PIN = {PRIMARY: "a_reference", FALLBACKS: None, EVERYWHERE: None, HEALTHY: "c_cl"}

# Azure Monitor counts from isolated single runs: arm -> run id in the region-count files.
AZURE_MONITOR = {
    "a_gw_retry": ("p6r_region_counts.json", "p6r_apim_retry_no_cb_r1"),
    "a_gw_cb3": ("p6r_region_counts.json", "p6r_apim_retry_cb_r1"),
    "a_gw_cb1": ("p6r_region_counts.json", "p6r_apim_retry_cb_trip1_r1"),
    "a_gw_priority": ("p6r_region_counts.json", "p6r_apim_priority_r1"),
    "a_cl_weighted_mem": ("p5r_region_counts.json", "p5r_direct_weighted_mem_r1"),
}

# Tabs: (group name, slug, colour, note). Matched-pair tabs first: they are the headline.
TABS = [
    (PRIMARY, "primary", "#9c6644",
     "Steady 2 requests a second for five minutes at 60,000 TPM per region, with 90% of traffic aimed at UK South, "
     "which can only serve about two thirds of that. Cards with a coloured edge go through the gateway; "
     "grey-edged cards are a client calling the regions directly. Where a setup was repeated, the card shows "
     "the middle result of its valid runs."),
    (FALLBACKS, "fallbacks", "#bc4749",
     "Steady 3 requests a second for five minutes at 60,000 TPM per region, with 90% aimed at UK South. "
     "The two fallback regions must take about 108 requests a minute between them, three quarters of what they can serve. "
     "Grey-edged cards are a client calling the regions directly."),
    (EVERYWHERE, "everywhere", "#264653",
     "Steady 6 requests a second for five minutes at 60,000 TPM per region, about 1.7 times what the three regions can serve "
     "(3.6 a second). The best any setup can do is about 60%. Grey-edged cards are a client calling the regions directly."),
    (HEALTHY, "healthy", "#6a994e",
     "Steady 1 request a second for five minutes at 60,000 TPM per region, an even split and no failures. "
     "This measures what the gateway costs when nothing is wrong. The grey-edged card is the reference."),
    ("No retry", "none", "#1f7a8c",
     "200-request bursts, 10,000 TPM per region. With no retry, nothing gets past about 17%. "
     "A breaker or a request cap on its own makes it worse, and the busiest run completes nothing."),
    ("Direct (no gateway)", "direct", "#5c6b73",
     "200-request bursts, 10,000 TPM per region. Calling Foundry directly gives the same result as the gateway with no policies. "
     "Walking the regions in order only burns calls."),
    ("Client retry", "client", "#e09f3e",
     "200-request bursts, 10,000 TPM per region. Short pauses do nothing useful. "
     "Only sleeping for the full Retry-After works, and it costs about 30 seconds a call."),
    ("Breaker and weights", "breaker", "#2a9d8f",
     "200-request bursts, 10,000 TPM per region. A gateway retry rule was set in these runs but never worked (a bug found later), "
     "so read them as breaker and weights only. Nearly all land at the same 16-18%, "
     "and two identical runs of one setup differ widely."),
    ("Quota to spare", "spare", "#8e7dbe",
     "200-request bursts, 60,000 TPM per region: six times the quota, so 200 requests fit inside one minute's allowance. "
     "A gateway retry rule was set but never worked, so these are even-split and skewed controls. "
     "The control from the 10,000 TPM runs is pinned for contrast."),
]

REFERENCE_BURST = ("baseline", "Reference, 10,000 TPM")
REFERENCE_TAG = "Reference"


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
def _vals(m: dict, key: str) -> dict:
    return m.get(key, {}).get("values", {})


def summarise(run_id: str) -> dict:
    j = json.loads((RESULTS / f"{run_id}.json").read_text())
    m = j["metrics"]
    dur = j["state"]["testRunDurationMs"] / 1000
    iters = int(_vals(m, "original_iterations").get("count") or m["iterations"]["values"]["count"])
    checks = {c["name"]: c for c in j["root_group"].get("checks", [])}
    if "eventual_successes" in m:
        succ = int(m["eventual_successes"]["values"]["count"])
    else:
        succ = int(checks["http 200 ok"]["passes"])
    calls = _vals(m, "total_http_calls").get("count")
    if calls is None and run_id == "direct_sequential":
        calls = int(m["http_reqs"]["values"]["count"])
    d = _vals(m, "http_req_duration")
    p50_all = d.get("med", d.get("p(50)"))
    ok = _vals(m, "http_req_duration{expected_response:true}")
    p50_ok = ok.get("med", ok.get("p(50)"))
    tts = _vals(m, "time_to_success")
    tts50 = tts.get("med", tts.get("p(50)"))
    tts95 = tts.get("p(95)")
    dropped = int(_vals(m, "dropped_iterations").get("count", 0))
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
        "tts_p95_ms": round(tts95, 1) if tts95 is not None else None,
        "dropped_iterations": dropped,
        "valid": bool(dur <= MAX_VALID_SECONDS and dropped == 0),
        "fast_refusals": bool(p50_all < 20),
    }


def run_ids_for(stem: str) -> list[str]:
    pat = re.compile(re.escape(stem) + r"_r(\d+)")
    found = [(int(pat.fullmatch(p.stem).group(1)), p.stem) for p in RESULTS.glob(f"{stem}_r*.json")
             if pat.fullmatch(p.stem)]
    return [rid for _, rid in sorted(found)]


def azure_monitor_summary() -> dict:
    out = {}
    for arm, (fname, key) in AZURE_MONITOR.items():
        rec = json.loads((RESULTS / fname).read_text())[key]
        orig = rec["orig"]
        calls = sum(rec["calls"].values())
        out[arm] = {
            "run_id": key,
            "requests": orig,
            "model_calls": calls,
            "calls_per_request": round(calls / orig, 2),
            "refused": sum(rec["t429"].values()),
            "by_region": rec["calls"],
        }
    return out


REGION_ID = re.compile(r"^rl([ABC])(?:_([a-z]+))?_r(\d+)(?:_x(\d+))?$")
REGION_NAMES = {"uksouth": "UK South", "westeurope": "West Europe", "swedencentral": "Sweden Central"}
REGION_CONDITIONS = {"A": "Direct, all regions together", "B": "Direct, one region at a time",
                     "C": "Through the gateway, pinned to one region"}
SPEED_PLANNED_S, SPEED_WALL_SLACK_S, SPEED_MIN_SAMPLES = 640, 30, 295


def region_speed() -> list[dict]:
    """Per-run, per-region latency from the speed tests (rl* runs). Valid runs only.

    Rule (fixed before the runs): discard a run with dropped iterations, a wall time more than 30 s
    over plan, any non-200 response, fewer than 295 measured samples for a region, or (gateway
    runs) an Azure Monitor pin check that failed.
    """
    out = []
    for p in sorted(RESULTS.glob("rl*.json")):
        if p.name.endswith((".meta.json", ".azmon.json", ".config.json")):
            continue
        mt = REGION_ID.match(p.stem)
        if not mt:
            continue
        j = json.loads(p.read_text())
        m = j["metrics"]
        wall = j["state"]["testRunDurationMs"] / 1000
        dropped = int(_vals(m, "dropped_iterations").get("count", 0))
        rows = []
        bad = dropped > 0 or wall > SPEED_PLANNED_S + SPEED_WALL_SLACK_S
        for key in REGION_NAMES:
            t = _vals(m, f"latency_{key}")
            if not t.get("count"):
                continue
            if int(_vals(m, f"non200_{key}").get("count", 0)) or t["count"] < SPEED_MIN_SAMPLES:
                bad = True
            rows.append((key, t))
        az = p.with_suffix(".azmon.json")
        if az.exists() and not json.loads(az.read_text()).get("ok", False):
            bad = True
        if bad:
            continue
        for key, t in rows:
            out.append({"run_id": p.stem, "condition": mt.group(1), "region": REGION_NAMES[key],
                        "samples": int(t["count"]), "median_ms": round(t["p(50)"], 1),
                        "p95_ms": round(t["p(95)"], 1)})
    return out


def ingest(path: Path) -> dict:
    old = json.loads(path.read_text()) if path.exists() else {}
    runs = []
    for run_id, (group, regime, quota, label, description) in RUNS.items():
        rec = {"run_id": run_id, "group": group, "regime": regime, "quota_tpm": quota,
               "label": label, "description": description}
        rec.update(summarise(run_id))
        runs.append(rec)
    for arm_id, arm in MATCHED.items():
        ids = arm.get("explicit") or [rid for stem in arm["stems"] for rid in run_ids_for(stem)]
        for rid in ids:
            rec = {"run_id": rid, "group": arm["tab"], "regime": "matched", "arm": arm_id,
                   "side": arm["side"], "quota_tpm": K60}
            rec.update(summarise(rid))
            runs.append(rec)
    return {
        "metrics": {
            "success_rate": "Eventual HTTP 200s with a valid body / original requests x 100",
            "throughput": "Original requests / wall-clock seconds",
            "goodput": "Successful completions / wall-clock seconds (= throughput x success rate)",
            "tts": "Time to success: first attempt to final valid answer, including retries and pauses",
        },
        "validity_rule": f"A matched-pair run is discarded if k6 ran for more than {MAX_VALID_SECONDS} s "
                         "(the laptop slept) or dropped iterations.",
        "source": old.get("source", "https://github.com/r-leyshon/azure-load-balance-perf"),
        "azure_monitor": azure_monitor_summary(),
        "region_speed": region_speed(),
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


def compact_ids(ids: list[str]) -> str:
    """Group run ids by stem: 'p6a_apim_retry_cb (r1, r3, r4)'. A stem with an unnumbered id lists full ids."""
    groups: dict[str, list[str]] = {}
    for rid in ids:
        m = re.fullmatch(r"(.*)_r(\d+)", rid)
        stem = m.group(1) if m else rid
        groups.setdefault(stem, []).append(rid)
    parts = []
    for stem, members in groups.items():
        if any(rid == stem for rid in members):
            parts.append(", ".join(members))
        else:
            ns = [rid[len(stem) + 1:] for rid in members]
            parts.append(f"{stem} ({', '.join(ns)})")
    return ", ".join(parts)


def arm_summary(arm_id: str, runs: list[dict], monitor: dict) -> dict:
    mine = [r for r in runs if r.get("arm") == arm_id]
    good = sorted((r for r in mine if r["valid"]), key=lambda r: r["run_id"])
    rates = [r["success_rate_pct"] for r in good]
    calls = [r["calls"] / r["iterations"] for r in good if r["calls"]]
    p50 = [r["tts_p50_ms"] for r in good if r["tts_p50_ms"]]
    p95 = [r["tts_p95_ms"] for r in good if r["tts_p95_ms"]]
    return {
        "arm_id": arm_id,
        "run_ids": [r["run_id"] for r in good],
        "rates": sorted(rates, reverse=True),
        "median": statistics.median(rates),
        "n": len(good),
        "excluded": len(mine) - len(good),
        "calls_per_request": statistics.median(calls) if calls else None,
        "throughput": statistics.median(r["throughput_rps"] for r in good),
        "goodput": statistics.median(r["goodput_rps"] for r in good),
        "p50": statistics.median(p50) if p50 else None,
        "p95": statistics.median(p95) if p95 else None,
        "monitor": monitor.get(arm_id),
    }


def matched_card(s: dict, tab_colour: str, maxima: dict, tag: str = "") -> str:
    arm = MATCHED[s["arm_id"]]
    colour = GREY if arm["side"] == "client" else tab_colour
    rates = ", ".join(f"{x:.1f}%" for x in s["rates"])
    meta = [f'{str(s["n"]) + " runs" if s["n"] > 1 else "One run"}: {rates}']
    if s["p50"] and s["p95"]:
        meta.append(f'Median answer {s["p50"]:.0f} ms &middot; p95 {s["p95"]:,.0f} ms')
    mon = s["monitor"]
    if mon:
        meta.append(f'Azure Monitor, one isolated run: {mon["calls_per_request"]:.2f} model calls per request, '
                    f'{mon["refused"]} of them refused')
    elif arm["side"] == "client" and s["calls_per_request"]:
        meta.append(f'{s["calls_per_request"]:.2f} model calls per request')
    if s["excluded"]:
        meta.append(f'{s["excluded"]} more run{"s" if s["excluded"] > 1 else ""} discarded (laptop slept)')
    bars = [
        bar("Success", s["median"], f'{s["median"]:.1f}%'),
        bar("Throughput", s["throughput"] / maxima["throughput"] * 100, f'{fmt_rate(s["throughput"])}/s'),
        bar("Goodput", s["goodput"] / maxima["goodput"] * 100, f'{fmt_rate(s["goodput"])}/s'),
    ]
    return card(arm["title"], compact_ids(s["run_ids"]), arm["desc"], bars, meta, colour, tag)


def grid(note: str, cards: list[str]) -> str:
    return f'<p class="tab-note">{html.escape(note)}</p>\n<div class="exp-grid">\n' + "\n".join(cards) + "\n</div>\n"


# Chart series for the steady-rate runs: arm -> (series name, colour). Symbol is set by side.
STEADY_RATE = {PRIMARY: 2, FALLBACKS: 3, EVERYWHERE: 6, HEALTHY: 1}
SERIES_NOTHING = ("Nothing: no retry, no sin bin", "#bc4749")
SERIES_RETRY = ("Retry only", "#e09f3e")
SERIES_FIRST = ("UK South first, nothing remembered", "#8e7dbe")
SERIES_BIN = ("Sin bin", "#2a9d8f")
STEADY_SERIES = {
    "a_reference": SERIES_NOTHING, "a_gw_cb5xx": SERIES_NOTHING,
    "a_gw_retry": SERIES_RETRY, "a_gw_retry0": SERIES_RETRY, "a_cl_weighted": SERIES_RETRY,
    "a_cl_seq": SERIES_FIRST, "b_cl_seq": SERIES_FIRST,
    "d_gw_priority": ("Gateway: priority list", "#264653"),
    "d_gw_cb1": ("Gateway: breaker, even split", "#2a9d8f"),
    "d_cl_seq_mem": ("Client: UK South first, cool-down", "#e9a23b"),
    "d_cl_weighted_mem": ("Client: even split, cool-down", "#e76f51"),
    "c_gw": ("Through the gateway", "#6a994e"),
    "c_cl": ("Direct to the regions", "#5c6b73"),
}
STEADY_VIEW = {PRIMARY: "main", FALLBACKS: "main", EVERYWHERE: "steady_every", HEALTHY: "healthy"}


def steady_points(runs: list[dict]) -> list[dict]:
    out = []
    for r in runs:
        if r["regime"] != "matched" or not r["valid"] or not r["tts_p95_ms"]:
            continue
        arm = MATCHED[r["arm"]]
        name, colour = STEADY_SERIES.get(r["arm"], SERIES_BIN)
        out.append({
            "run_id": r["run_id"], "view": STEADY_VIEW[r["group"]], "title": arm["title"], "side": arm["side"],
            "series": name, "colour": colour, "rate": STEADY_RATE[r["group"]],
            "successes": r["successes"], "iterations": r["iterations"], "success_rate_pct": r["success_rate_pct"],
            "median_ms": r["tts_p50_ms"], "p95_ms": r["tts_p95_ms"],
            "throughput_rps": r["throughput_rps"], "goodput_rps": r["goodput_rps"],
            "calls_per_request": round(r["calls"] / r["iterations"], 2) if arm["side"] == "client" and r["calls"] else None,
        })
    return out


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
    monitor = data.get("azure_monitor", {})
    by_id = {r["run_id"]: r for r in runs if r["regime"] == B}
    colours = {name: colour for name, _, colour, _ in TABS}

    burst = [r for r in runs if r["regime"] == B]
    maxima = {
        "throughput": max(r["throughput_rps"] for r in burst),
        "goodput": max(r["goodput_rps"] for r in burst),
    }
    arms = {a: arm_summary(a, [r for r in runs if r["regime"] == "matched"], monitor) for a in MATCHED}

    for name, slug, colour, note in TABS:
        cards: list[str] = []
        if any(a["tab"] == name for a in MATCHED.values()):
            members = [s for a, s in arms.items() if MATCHED[a]["tab"] == name]
            pin = MATCHED_PIN.get(name)
            ordered = sorted(members, key=lambda s: (-s["median"], s["p95"] or 1e9))
            tab_max = {"throughput": max(s["throughput"] for s in members),
                       "goodput": max(s["goodput"] for s in members)}
            if pin:
                cards.append(matched_card(arms[pin], colour, tab_max, REFERENCE_TAG))
            cards += [matched_card(s, colour, tab_max) for s in ordered if s["arm_id"] != pin]
        else:
            members = [r for r in burst if r["group"] == name]
            pin_id, pin_tag = REFERENCE_BURST
            ordered = sorted(members, key=sort_key)
            in_group = any(r["run_id"] == pin_id for r in members)
            cards.append(burst_card(by_id[pin_id], maxima, colours[by_id[pin_id]["group"]], pin_tag))
            cards += [burst_card(r, maxima, colour) for r in ordered if not (in_group and r["run_id"] == pin_id)]
        (INC / f"24-runs-{slug}.html").write_text(grid(note, cards))

    # Remove include files from previous designs.
    live = {f"24-runs-{slug}.html" for _, slug, _, _ in TABS}
    for f in INC.glob("24-runs-*.html"):
        if f.name not in live:
            f.unlink()

    # Chart data: bursts (throughput against success), steady-rate runs and the region speed tests.
    chart = {**{k: v for k, v in data.items() if k not in ("runs", "azure_monitor", "region_speed")},
             "steady": steady_points(runs), "region_speed": data.get("region_speed", []), "runs": [
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

    for s in sorted(arms.values(), key=lambda s: (MATCHED[s["arm_id"]]["tab"], -s["median"])):
        print(f'{MATCHED[s["arm_id"]]["tab"][:18]:18s} {s["arm_id"]:18s} n={s["n"]} excl={s["excluded"]} '
              f'median {s["median"]:.1f}  p50 {s["p50"]} p95 {s["p95"]}  {s["rates"]}')
    print(f"{len(runs)} runs ({len(burst)} burst); wrote runs.json, scatter.html and {len(TABS)} include files")


if __name__ == "__main__":
    main()
