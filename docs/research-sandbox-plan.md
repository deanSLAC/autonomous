# Research sandbox — implementation plan

A place the autonomy agents can send a hard analysis question and get a written
answer back, where the answering process may run arbitrary Python and reach the
web, and cannot touch hardware, the ongoing collection, or any credential that
matters.

Status: plan only, nothing built. Written 2026-09-11.

## Why a container and not a wider allowlist

`playground` already runs an agent with `Bash(python3 *)`, `curl`, `wget`,
`WebSearch` and `WebFetch` enabled. It is restricted by a deny list in a
settings file and by nothing else. That is acceptable for a testbed on a
workstation and not acceptable on the machine that owns SPEC, because a
settings-file allowlist is a pattern match on a command string, and the agent
auto-approves read-only shell commands regardless of it.

The rule to carry over from `chemcat`, which solved this already: **moving
execution somewhere a kernel can enforce the boundary is what makes it safe to
widen the allowlist.** The settings file stays as the coarse filter. The
container is the boundary.

## The template

`spec_docker` is the working precedent on this host, and this service should be
a sibling of it rather than a new idea. What it already gets right, and what to
copy verbatim:

- A small FastAPI service bound to `127.0.0.1`, one ephemeral container per
  request, `docker run --rm` with a name so a timeout can `docker kill` it.
- `--read-only` root with an explicit `--tmpfs /tmp`, `--memory`, `--cpus`,
  `--pids-limit`.
- A per-run work directory bind-mounted at a fixed path, so results are
  inspectable afterwards and the caller never has to parse container stdout for
  files.
- A hard `subprocess.run(timeout=...)` around the whole thing.
- The API is unit-testable on a workstation without Docker or the payload
  installed; only real runs need the host.

Two things differ, and both are the whole design problem:

1. `spec-eval` runs with `--network none`. This one needs the LLM gateway and
   the web, so egress has to be shaped rather than removed.
2. `spec-eval` holds no credential. This one holds an LLM gateway key.

## Proposed shape

A new sibling repo, `research_docker/`, laid out like `spec_docker`:
`api/` (host-side FastAPI), `image/` (the Dockerfile), `scripts/`
(build/start). Autonomy consumes it over HTTP exactly as it already consumes
`SPEC_EVAL_URL`, so the seam is identical to one the codebase already has.

### The container

Base `python:3.12-slim`, plus the scientific stack the toolbelt already needs
(numpy, scipy, pandas, lmfit, xraydb, matplotlib), the `beamtimehero_cli`
science modules, and the `claude` CLI. Pin the CLI install rather than piping
an unpinned installer to a shell — `chemcat`'s image does the latter and it is
the one soft spot in an otherwise careful supply chain.

Run flags, extending the `spec-eval` set:

```
docker run --rm --name research-<run_id>
  --user 1000:1000
  --cap-drop ALL --security-opt no-new-privileges
  --read-only --tmpfs /tmp:rw,size=2g
  --memory 4g --cpus 2 --pids-limit 512
  -v <experiment_scan_dir>:/data:ro
  -v <run_dir>:/work:rw
  --network research-egress
  <image> /usr/local/bin/entrypoint
```

`--memory 4g` rather than 2g: a Fourier transform over a full EXAFS set in
numpy will exceed 2g. `--cpus 2` is a ceiling that leaves the collection
process its share — pick it against the host's core count, and cap concurrency
at one or two runs.

### Egress

The requirement is the LLM gateway and general HTTPS, and specifically *not*
the beamline. Preferred approach, because it reuses infrastructure that already
exists here: give the container no direct route and only an `HTTPS_PROXY`
pointing at the SLAC outbound proxy, so the proxy is the allowlist and the
beamline subnet is simply not reachable through it. Failing that, a dedicated
docker network with explicit rules dropping RFC1918 destinations except the
gateway.

Either way the test is the same, and it belongs in the suite: from inside a
running sandbox, the SPEC host and the beamline subnet must be unreachable.

### The environment is built, not inherited

Copy `chemcat/chat/execution.py` directly here. The child environment is an
explicit allowlist: the gateway URL, the gateway token, `HTTPS_PROXY`, `HOME`,
`PATH`. Nothing else. No `SPEC_*`, no `SPEC_TRANSPORT`, no `ORCHESTRATION_DB_PATH`,
no `BEAMLINE_TOOLS_DB_PATH`, no `SLACK_BOT_TOKEN`, no `BEAMTIMEHERO_SAFETY_SWITCHES`.
`os.environ.copy()` is the bug; never write it.

Use a **separate gateway key** for the sandbox. It is the one credential inside
the boundary, so it should be separately revocable, and its usage should be
attributable. `chemcat` notes that sharing keys across apps makes rate-limit
incidents collide; the same applies here, and the sandbox is the component most
likely to burn tokens unexpectedly.

### Settings file

A third settings file alongside the existing pair, `agent.research.settings.json`,
following `chemcat`'s rule that widening a context means an additional file and
never an edit to the existing one:

- allow: `Bash(python3 *)`, `Read(/data/**)`, `Read(./**)`,
  `Write(/work/**)`, `Edit(/work/**)`, `Glob`, `Grep`, `WebSearch`, `WebFetch`
- deny: `Bash(beamtimehero *)` in its entirety, plus the standard spine —
  `git`, `curl`, `wget`, `ssh`, `rm`, `mv`, env-prefix smuggling
  (`Bash(*=* ...)`), `Read(.env*)`, `Task`, `Agent`

Denying the whole `beamtimehero` command is deliberate. The sandbox is for
analysis of data it has been handed; it is not a second route to the tool
surface, and it has no SPEC transport configured to reach anyway.

## The calling surface

One tool, on its own tree so it can be allowlisted independently of everything
else — `research ask-question`, not another leaf under `tool`.

```
research ask-question --question <text> --experiment-id <id>
                      [--scans <list>] [--timeout-s 900] [--max-turns 40]
```

Returns the report text, the paths of any figures written to the run dir, the
turn and token count, and whether it hit a cap.

Four properties this tool must have:

- **It is a tool, not a delegate.** The calling agent gets a report and remains
  the only thing that can act. Nothing inside the sandbox may enqueue a motor
  move, write a steering row, or touch a file the orchestrator reads.
- **It is budgeted.** Wall clock enforced by the service the way `spec-eval`
  does it; `--max-turns` passed to the CLI; a token ceiling read from the
  stream-json result event, killing the container when exceeded. Autonomy has
  no cap of any kind today, and this is the wrong component to discover that
  in.
- **It is audited.** The question and the returned report go into the action
  log as a query row, so a sandbox consultation appears in the experiment
  record next to the decisions it informed.
- **Its output is untrusted input.** The sandbox reads the open web, so a page
  can contain text aimed at whatever reads the report — and what reads the
  report is the planner, which does act on the beamline. The planner prompt
  must treat a sandbox report as evidence to weigh, never as instructions to
  follow, and the report should be delivered wrapped and labelled as
  third-party content. This is the one attack path the container does not
  close, and it is closed by prompt discipline plus the fact that every actual
  motion still goes through a justified, allowlisted, switch-gated tool.

## Phasing

1. **Decide egress and get a dedicated gateway key.** Blocking, and it is a
   conversation with networking rather than code.
2. **Image, runner, `/research` endpoint — no LLM yet.** The endpoint executes a
   supplied Python file in the sandbox and returns stdout plus the run dir.
   This is where the isolation gets proven, before anything unpredictable runs
   inside it.
3. **Add the agent.** `claude -p` with the research settings file, stream-json
   parsed the way `orchestration/agent/claude_code_client.py` already parses it.
4. **Wire the tool.** New `research` tree, caps enforced, action-log row,
   report wrapped as untrusted content.
5. **Leave it off by default.** Off unless a config flag turns it on, so the
   first beamtime that uses it does so deliberately.

## Isolation test suite

These run from inside a live sandbox container and are the acceptance criteria
for phase 2. Each must fail to reach its target:

- No `SPEC_*` variable present in the environment.
- The SPEC host and port: TCP connect fails.
- The beamline subnet: unreachable.
- `https://<llm gateway>`: reachable. A general HTTPS host: reachable.
- `/data`: readable, and a write to it fails with `EROFS`.
- `/work`: writable.
- The orchestration DB path and the action-log DB path: absent, and not
  writable if the path is guessed.
- The safety-switches file: absent, and a write to its path fails.
- The root filesystem: read-only outside `/tmp` and `/work`.
- Process count and memory ceilings: enforced (fork bomb and allocation loop
  both die rather than affecting the host).

## Open questions

- Where the run directories live, and who reaps them. `spec_docker` keeps them
  forever under a shared root; for figures that is probably right, but it needs
  a retention rule.
- Whether `chemcat` should eventually call the same service. Its per-session
  pod already does this job inside Kubernetes, so the likely answer is no, and
  the two stay parallel implementations of one pattern.
- Whether the sandbox should get read access to the action log so it can answer
  "what has this experiment already tried". Useful, and it widens the read
  surface; probably a later phase with a narrow view rather than the DB.
