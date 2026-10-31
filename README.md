# ProbeBudget — Datadog-inspired diagnostic capture experiments

Datadog provides observability and runtime debugging. ProbeBudget investigates which explicitly allowed probes can distinguish authored competing faults while staying within a telemetry byte budget.

**Implemented:** an actual loopback HTTP checkout service, injected stale-cache/downstream/retry faults, real request timings, a pre-serialization field allowlist, exact emitted-frame byte accounting, measured capture/process CPU times, and a budgeted information selector with baselines. **Integration unverified:** there is no Datadog agent/tracer, remote instrumentation, OpenTelemetry adapter, learned fault model, or production diagnosis. Python keeps the fixture and planner small; this workload has no inference kernel that would benefit from C++.

```sh
python -m unittest discover -v
python probebudget.py --seed 7 --output demo.json
```

Python 3.11+; standard library only. The demo starts ephemeral localhost servers, performs real HTTP requests, and closes them. No account, external service, credentials, or deployment is needed. `demo.json` retains each capture, calibration, byte/CPU measurement, probe order, candidate set, and diagnosis. Local timings vary; they are illustrative measurements, not stable performance claims.

## Mechanism

The service executes a checkout with a cache age, downstream sleep duration, and actual downstream-attempt loop. Stale cache changes the returned price; slow downstream sleeps 6ms; retry amplification performs three requests. A separate unmodeled fault burns CPU while exposing otherwise healthy probe values. A compound control combines stale cache and retries. The initial symptom is derived from observed request duration (>3.5ms) or incorrect price.

The planner never receives the fixture fault label. Its three independent observed features are a stale-age flag, measured downstream latency band, and counted attempts. Their combination yields eight authored signatures, including compound alternatives. The planner chooses entropy gain per measured frame byte, but **requires all three features before identifying a single fault**: a partial match cannot exclude an unmodeled or concurrent problem. Compound, contradictory, unstable, unmodeled, and under-budget evidence produces an abstention. An unknown fault that exactly mimics a known full signature remains indistinguishable; this is a declared model limit.

Calibration executes all six scenarios and records maximum encoded frame sizes. Each request enforces the remaining actual budget independently; estimated costs cannot override the sink. A literal allowlist constructs each frame before JSON encoding. A planted token in internal authorization and nested password fields must be absent from every captured frame and HTTP report. No stack, object, locals, or arbitrary field dumping is used.

**Budget scope:** compact UTF-8 newline JSON probe frames only. HTTP headers, ordinary service responses, calibration traffic, and fixed report metadata are excluded. These excluded bytes are not free production telemetry. CPU values use process-wide `process_time_ns` around fixture execution/capture in the same process, and can include concurrent runtime work; they do not establish profiler overhead or isolated per-thread CPU. HTTP request counts and summed service latency are retained separately. Each adaptive observation executes a fresh request against a stable injected scenario; this does not recover the original request's lost variables.

## Recorded comparison

The checked-in local seed-7 run uses a 170-byte **per-incident frame** budget. This authored budget fits the three decisive probes (~134–135 bytes), but adding a decorative heartbeat can prevent complete verification; context costs 542 bytes. It is a transparent stress scenario, not a representative industry distribution.

| Strategy | Healthy/single-fault matches (of 4) | Adverse abstentions (of 2) | Total frame bytes, 6 cases | Budget violations |
|---|---:|---:|---:|---:|
| Information per byte | 4 | 2 | 806 | 0 |
| Cheapest first | 0 | 2 | 784 | 0 |
| Seeded random | 0 | 2 | 830 | 0 |
| All probes, unconstrained baseline | 4 | 2 | 4,334 | 6 |

All-probes deliberately ignores the budget to measure the acquisition-cost baseline; it is never described as budget compliant. Cheapest/random can waste enough budget to abstain. Healthy, compound, and unmodeled cases are explicit controls. Results cover only six authored fixtures and one random ordering; they do not estimate production accuracy or prove the planner generally optimal. Timing noise may change symptoms and correctly causes abstention.

## Validation and next stages

Eight tests cover real HTTP fault diagnosis, compound/unmodeled abstention, zero/partial budgets, exact byte accounting and privacy, expensive all-probe behavior, malformed requests without service actions, incomplete-signature abstention, and actual CPU/request measurements. Secrets are absent from emitted telemetry; they are intentionally present in fixture source as a test canary.

Next: repeated seeds and broader arrival/load controls, isolated instrumentation-overhead trials, then an explicitly permissioned Datadog/OpenTelemetry adapter. Arbitrary production systems, runtime code injection, and secret scrubbing heuristics are outside this milestone.

## Primary research

Datadog already supports dynamic instrumentation, debugger redaction, and exception snapshots. This is an acquisition-policy experiment around existing capabilities, not a claim that those products are absent.

- [Dynamic instrumentation](https://docs.datadoghq.com/tracing/dynamic_instrumentation/)
- [Host-side sensitive data scrubbing](https://docs.datadoghq.com/tracing/live_debugger/sensitive-data-scrubbing/?lang_pref=en)
- [Exception Replay and missing context](https://docs.datadoghq.com/error_tracking/backend/exception_replay/)
