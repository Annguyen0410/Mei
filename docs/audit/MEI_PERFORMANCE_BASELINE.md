# Mei — Performance Baseline

## 1. Status

**No performance measurements were taken in this session.** The environment is a
headless coding session without an interactive Windows desktop, GPU inspection
or a stable way to drive 5–50 real tabs through a packaged build. Reporting
numbers here would be fabrication, so this document records the method and the
gap instead.

What *was* done: the hibernation decision is now conservative (a policy module),
which can only reduce forced renderer disposal. No performance improvement is
claimed from it, because it was not measured.

## 2. Method (run this on a real desktop)

Machine record (fill before every run):

```
CPU:            <model, cores/threads>
RAM:            <GB, speed>
GPU:            <model, driver>
Disk:           <SSD/HDD, free GB>
OS:             <Windows build>
Python:         3.11.x
PyQt6:          6.11.0
QtWebEngine:    6.11.0 (Chromium 140.x)
Mei version:    1.0.1.0
Profile:        fresh test profile (never the user's real profile)
```

Procedure:

1. Create a throwaway data root: `set LITEBROWSER_DATA_DIR=%TEMP%\mei-perf`.
2. Launch with a fixed tab set (repeatable URLs, no sign-in).
3. For each tab count N ∈ {5, 10, 20, 30, 40, 50}:
   - wait for `loadFinished` on every tab plus 10 s settle;
   - record working set of the Mei process;
   - record child `QtWebEngineProcess.exe` working sets;
   - record CPU average over 60 s idle and peak during load;
   - switch to tab N and back, measure wake latency (first paint);
   - hibernate 10 background tabs, measure RSS delta and wake latency;
   - count live renderer processes.
4. Session restore: quit, relaunch, measure time until the tab desk is shown
   and until the active tab paints.
5. Repeat each configuration 3 times; report median and range, not a best case.

Suggested harness: `tools/` already has `run_at_hour.py` and
`engine_report.py`; add `tools/perf_probe.py` that emits JSON so results are
diffable. Do not add a GUI dependency for this.

## 3. Metrics that must be collected

| Metric | Why |
|---|---|
| Startup → first window | perceived launch quality |
| First tab render | real cold-start cost |
| New tab creation | UI responsiveness |
| Tab switch | hibernation wake cost |
| Hibernate (RSS before/after) | whether disposal actually frees memory |
| Wake latency | user-visible cost of hibernation |
| Session restore | crash/relaunch recovery |
| History/bookmark search | 10k-entry scaling |
| Download/upload throughput | IPC path overhead |
| PDF/video/WebGL render | engine/GPU health |
| Multi-window RSS | profile sharing cost |
| CPU idle over 8 h | timer/signal leaks |

## 4. Performance budgets (proposed, not yet enforced)

These are **targets to validate**, not achieved results:

* cold start to first window ≤ 3 s on SSD;
* new tab ≤ 300 ms;
* tab switch (live) ≤ 150 ms; wake from hibernation ≤ 1.5 s (network-bound);
* idle CPU ≤ 1 % with 10 tabs and no media;
* RSS growth ≤ 5 % over 8 h idle with a fixed tab set;
* no monotonic growth in `QWebEngineView`/`QTimer` object counts across 100
  open/close cycles.

A budget that has never been measured is a wish; do not mark the performance gate
green until §2 has been run twice on the same machine.

## 5. Long-duration stability

Not run. Required harness: fixed tab set, 8/24/48/72 h, sampling every 60 s of
RSS, CPU, handle count, thread count, renderer count; plus a 100× open/close
loop checking that `QWebEngineView` and `QTimer` instances are released
(`sip.isdeleted`) and that signal connections do not grow.

Known code-level risks to watch:

* profile-scoped `QWebEngineScript` objects are inserted per profile; repeated
  insertion of the same name is guarded, but a profile churn test is warranted;
* hibernate/wake cycles create a new `QWebEngineView` and timer each time;
* `prefs` caches keyed by profile path never shrink;
* the favicon cache is capped (512) but cleared wholesale.

## 6. What changed in this batch that needs measuring

1. Removed a DocumentCreation script that ran on every page and every subframe.
   Expected effect: slightly lower per-page cost and less main-world work. **Not
   measured.**
2. Hibernation now refuses more tabs (audio/download/incognito/recent). Expected
   effect: more live renderers under media-heavy workloads, i.e. **higher** RSS
   in exchange for not destroying work. This is an intentional trade, and the
   reason adaptive thresholds must be measured before being tuned.
3. Truthful UA/Client Hints reduces header fabrication but does not change
   network volume materially.

## 7. Adaptive memory policy — not implemented

`MEMORY_SAVER_RSS_THRESHOLD_MB = 800` is a fixed constant in
`ui/main_window/window.py`. Replacing it with a policy based on total/available
RAM and renderer count is P1 work; it must not be done by polling faster than
once every few seconds, and it must never override the hibernation policy's
safety blockers.
