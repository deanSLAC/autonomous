# Guide: post-run log forensics

A repeatable workflow for sweeping the `logs/` directory after a beamtime run to surface errors, retry loops, agent confusion, and log-hygiene issues. Designed to be cheap (parallel subagents, severity-tiered, de-duplicated) and to feed directly into a commit-mapping pass that says which findings the team has already addressed.

## 1. Isolate the run

The flat `logs/` layout means files from many runs intermix. Bound the set to "this run only" first.

```bash
date                                                   # current local time
find logs/ -maxdepth 1 -type f -mmin -480 \            # mtime within past 8h (tune to taste)
  -printf "%TY-%Tm-%Td %TH:%TM  %s  %f\n" | sort
```

`server.log` is monolithic — it spans many runs. Find the offset where the run starts:

```bash
grep -n "^2026-05-10 17:36" logs/server.log | head -3
```

Record the start line. Every later step that touches `server.log` should be scoped to lines after that (e.g. `awk 'NR>=4962' logs/server.log | ...`).

## 2. Group by source type

The system emits six log categories. Each gets its own subagent.

| Source type | Filename pattern | Notes |
|---|---|---|
| beamline_alignment | `phase_beamline_alignment_*.log` | 1–2 per run |
| sample_alignment | `phase_sample_alignment_*.log` | 1–2 per run |
| sample_survey | `phase_sample_survey_*.log` | 1–2 per run |
| planner | `phase_planner_*.log` | many ticks per run |
| collection | `phase_collection_*.log` | usually one large file (~10 MB) |
| server | `server.log` (windowed slice) | start/end line offsets from step 1 |

## 3. Dispatch one analyzer subagent per source type, in parallel

Send all six in a single message. Each prompt should:

- **State what the phase does.** A subagent that knows what beamline-alignment vs sample-survey is can interpret confusion markers correctly.
- **Specify the signals.** ERROR, CRITICAL, Traceback, Exception, "failed", "error:"; WARNING in context; `retry`/`retrying`; long gaps in consecutive timestamps (model stall); repeated identical tool calls (stuck loop); agent narrative markers ("hmm", "wait", "actually", "let me reconsider", "this is unexpected", "I'm not sure"); argparse rejections; permission denials.
- **Use a 4-tier severity rubric keyed to operational impact**, not log volume:
  - **CRITICAL** — phase aborted, data lost, sample damaged, human had to intervene.
  - **HIGH** — agent retried/replanned/took a detour; bug worth fixing.
  - **MEDIUM** — noisy or suboptimal but recovered; log hygiene.
  - **LOW** — cosmetic, known-benign.
- **Demand de-duplication.** "Same root cause across N occurrences" = ONE finding with frequency = N.
- **Demand sampling, not reading.** Files are big. Tell the subagent: `grep -c` first to count repeats; only `Read` with `offset`/`limit` to inspect distinct issues; never read >500 lines at once.
- **Cap report length** (e.g. 1500-2200 words). Require a markdown table (`Severity | Finding | Where | Frequency | Why it matters`) plus a short prose summary.

Useful grep recipes the subagents should know:

```bash
grep -E -c "ERROR|Traceback|Exception|CRITICAL|failed" <file>
grep -n -i -E "converged|verdict|efficiency|damage" <file> | head -50
awk 'NR>=4962' logs/server.log | grep -E "WARNING|ERROR" | sort | uniq -c | sort -rn | head -50
```

## 4. Consolidate findings

Merge each phase's table into one severity-sorted master table with stable IDs (e.g. `BA1`, `SA3`, `P4`). Track at least:

- ID, severity, phase, one-line finding, file:line or grep-pattern reference, frequency.

## 5. Map findings → recent commits

Dispatch one final subagent. Give it: (a) the full consolidated finding list with IDs, (b) the relevant commit window (e.g. `git log --since='<time>' --pretty=format:'%h %ad %s'`), and (c) the uncommitted working-tree changes (`git status -s` + relevant `git diff` snippets).

Demand that the subagent **read the actual diffs**, not just commit messages — message titles overstate scope. Label each finding as:

- **Addressed** — a commit / change directly resolves the root cause.
- **Partially addressed** — touches the area but the underlying bug stays.
- **Unaddressed** — no recent change touches this.

## 6. Produce two final tables

1. **Addressed / Partial** — ID, status, commit hash(es), file paths, note.
2. **Unaddressed** — ID, severity, why it still matters.

Close with a short "top 3 to fix first" prose paragraph weighted by cost-per-line-of-code: the cheapest high-impact unfixed items.

## Subagent ergonomics

- All six analyzers run in parallel — one message, six tool calls. They share no context, so each prompt must be self-contained.
- The commit-mapping subagent runs **after** all six analyzers report, with the consolidated findings as input.
- A single foreground synthesizer (you) collects, de-duplicates, and writes the final report.

## When to use this

After every multi-phase beamtime run, before the team's next planning session. Cheap enough to be the default post-run hygiene; thorough enough to catch the issues that don't crash but eat time.
