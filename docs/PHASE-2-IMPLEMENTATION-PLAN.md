# Phase 2 Implementation Plan — The Agent Runtime

**Goal.** Make an agent actually run. Replace the scripted stand-in from Phase 1
with a real, model-backed agent that reasons under pinned instructions, produces
an artifact, and is recorded exactly as the scripted one was.

**Scope, from `ARCHITECTURE.md` §37.** That section's suggested order puts
*"LLM Port with a deterministic fake, then one real agent"* immediately after the
Execution Record Core. Phase 2 is that step, and only that step. The Tool Gateway
with real tools is §37's next item and stays out.

**Status.** Plan only. No code until this is approved.

---

## 1. Where Phase 1 left off

Phase 1 built the record and proved it: 401 tests, `E-1042` driven end to end,
reconstructed from the database alone, and tamper-detected on both chains.

What exists and Phase 2 builds directly on:

| Built | What Phase 2 does with it |
|---|---|
| Audit chain, anchors, verification | Every agent step lands in the same chain, unchanged |
| Task machine, `task_service` | The runtime moves tasks through it |
| Action lifecycle + evidence | An agent's model calls become actions with evidence |
| Artifact versions, immutable | The agent's output becomes a version |
| Gate engine, `figures_traceable` | Judges what the agent wrote |
| Rework controller | Sends it back when the gate fails |
| KeyStore, BlobStore, redaction | Model prompts and completions are payloads like any other |
| Dispatch queue, worker loop | Runs agent tasks instead of scripted ones |

**Nothing in Phase 1 changes.** If Phase 2 requires editing the audit chain, the
gate engine, or the isolation model, something has been designed wrong — that is
the signal to stop, not to widen.

## 2. What Phase 2 builds

Six components. Each earns its place by making the one before it usable.

### 2.1 LLM Port (`adw/ports/llm.py`)

**What.** A provider-neutral interface: a completion request in, a completion or
a tool-call proposal out, with token usage attached.

**Why.** `CLAUDE.md` §6 requires provider-specific code behind an abstraction and
business logic testable with no live model. D8 fixes the requirements — a single
provider, contractually bound to zero retention and no training.

**Connects to.** Nothing below it. It is a boundary, and the Agent Runtime is its
only caller.

**Must not.** Decide what to send. Execute anything. See a secret. Leak a
provider concept — a message role, a tool-call schema, a finish reason — into any
caller.

### 2.2 Deterministic fake provider (`adw/adapters/llm_fake.py`)

**What.** A scripted provider: given a request matching a recorded pattern, it
returns a recorded response. Same interface, no network.

**Why.** This is the component that keeps the whole suite runnable and
deterministic. Without it every test involving an agent becomes slow, flaky, and
dependent on a vendor. `CLAUDE.md` §6 asks for exactly this.

It is also the honest mitigation for D8's stated limitation: *an abstraction
validated against exactly one provider is a hypothesis*. A second implementation
does not prove portability, but it does prove the interface is implementable
twice.

**Connects to.** The LLM Port, and every test.

**Must not.** Ship enabled outside `dev` and `test` — the same refusal the local
key store and blob store already carry.

### 2.3 Real provider adapter (`adw/adapters/llm_<provider>.py`)

**What.** One adapter for the selected provider.

**Why.** Something has to actually call a model.

**Blocked** on provider selection — see §5.

**Must not.** Be imported by any test. The fake is what tests use.

### 2.4 Definition and skill authoring (open decision **F**)

**What.** Where agent definitions and skills live, and how a version reaches a
running task.

**Why.** Phase 1 seeded definitions from fixtures because pinning only needed
*something* to pin. Phase 2 needs real instruction content, versioned, immutable
once referenced, and resolvable at task start.

**Connects to.** `agent_definition_version` and `skill_version`, already built,
already immutable by trigger. This adds authoring and resolution, not schema.

**Must not.** Let a Skill confer a capability (D10). A Skill is instruction
content; capability arrives only through a grant. That separation is what stops
injected content from escalating privilege, and it is the reason the two are
separate tables.

### 2.5 Agent Runtime (`adw/runtime/agent_runtime.py`)

**What.** The component that executes one task under one pinned Agent Definition
version: assemble context, call the model, interpret the response, record
everything, stop when the completion criteria are met or a limit trips.

**Why.** It is the blast-radius container. `ARCHITECTURE.md` §10 makes it the
least-trusted component in the system, and Phase 2 is where that stops being
hypothetical.

**Connects to.** LLM Port, `task_service`, `action_recorder`, `evidence_recorder`,
`artifact_service`.

**Must not** — and these are the load-bearing ones:

- Hold database credentials of its own, beyond the session it is handed.
- Execute a tool. It may only *propose* one (I2). Phase 2 has no gateway, so a
  proposal is recorded and refused, which is the correct behaviour and worth a
  test.
- Treat model output as instructions. Everything the model returns is data.
- Survive its task.

**Context assembly** is where D13 lives. Pinned instructions and pinned skill
content are *instructions*; task inputs, prior artifact content, and anything
that arrived from outside are *data*, structurally separated and labelled as
untrusted. Nothing in the data region may alter permission, skip a gate, or
change the plan — and because the runtime cannot execute anything anyway, the
worst an injection achieves is a bad artifact, which is what the gates are for.

### 2.6 Cost accounting and limits

**What.** Token usage recorded per action; per-execution and per-tenant budgets
with hard stops.

**Why.** `PRODUCT.md` §25 makes these hard stops rather than alerts, and D11's
rework cap is already enforced — an agent loop is the other unbounded spend path.
A breach pauses and escalates; it never silently truncates work, because a
partial artifact produced without saying so would violate the platform's core
claim.

**Connects to.** The Action record, the audit chain, and the Needs Attention
queue built in Phase 1.

---

## 3. The deliverable

**`E-1042` runs again, with the scripted agent replaced by a real one.**

Phase 1's scenario test hard-codes the wrong figure and then the right one. Phase
2's version hands the Commentary Agent a dataset and a pinned instruction, and the
agent writes the narrative itself — against the fake provider, scripted to produce
an unsourced figure on the first attempt and a sourced one after rework.

Everything downstream is untouched: G4 catches it, rework opens, v2 passes, a
human signs, the chain verifies, and the execution reconstructs from the database
alone. **If any Phase 1 test needs changing to accommodate a real agent, that is a
finding to report, not a fix to apply.**

Why the Commentary Agent specifically: it is the one agent in the Finance plan
whose work is pure reasoning over data it is given. No spreadsheet, no chart, no
PDF — so it needs no tools, which is exactly what makes it the right first agent
while the Tool Gateway is still ahead of us.

---

## 4. Sequence

Seven tasks, each independently testable and committable.

| # | Task | Deliverable |
|---|---|---|
| 1 | LLM Port + fake provider | Fake satisfies the port; refuses outside dev/test |
| 2 | Definition and skill authoring (**F**) | A versioned instruction set resolves for a task |
| 3 | Context assembly with untrusted-data separation | Injection tests pass |
| 4 | Agent Runtime loop, recording actions and evidence | A model call becomes an action with evidence |
| 5 | Tool-call proposals recorded and refused | I2 proved with no gateway present |
| 6 | Cost accounting and hard stops | Budget breach pauses and escalates |
| 7 | Real provider adapter + `E-1042` with a live agent | Scenario passes against the fake; adapter smoke-tested against the real provider |

**Definition of done:** the full suite green including a rewritten `E-1042`, all
existing quality gates passing, no Phase 1 test modified to accommodate Phase 2,
and the scenario suite running with **no network access**.

---

## 5. Genuinely blocking decisions

Two. Everything else in Phase 2 is derivable from the documents.

**B1 — Which LLM provider.** `PRODUCT.md` §26 #8 and D8 remain open: the
*requirements* are fixed (single provider, contractual zero retention, no training
on customer data), the selection is not. This blocks task 7 only. Tasks 1–6 run
entirely on the fake, so Phase 2 can start today and stall only at the last step.

D8 also notes the provider must be disclosed as a subprocessor under a DPA — a
provider that cannot commit contractually is unusable regardless of model quality.
That is a procurement decision, not an engineering one.

**B2 — Open decision F: where definitions and skills live.** Versioned files
shipped with the platform, or database records with an authoring surface.
`DECISIONS.md` D5 fixes *who* may author them in MVP (platform-curated only); it
does not fix *where they live*. This blocks task 2, which blocks everything after
it, so it needs deciding first.

The trade-off, stated without recommending: files get code review, diffs, and
release discipline for free, and make a definition change a deploy. Database
records make a definition change an operation rather than a release, and are the
path D5's post-MVP tenant authoring will eventually need — but they need their own
authoring, review, and rollback story, which files get from git.

## 6. Not blocking, but worth knowing

- **Model tiering** (`PRODUCT.md` §26 #9) stays open. Phase 2 uses one model; the
  port is where tiering would attach later.
- **The Orchestrator is not in Phase 2.** Phase 2 runs a task that already exists;
  it does not plan one. That is deliberate — planning needs the **Execution state
  machine**, whose transitions remain blocked on unresolved product decisions
  (`transitions.py`). Phase 3 or 4 will need those resolved before an orchestrator
  can exist.
- **Open decision G** (idempotency for tool calls) arrives with the Tool Gateway,
  not here. Phase 2 makes no external call other than to the model provider.
- **P6**, the PDF library spike, is still unstarted and belongs with real tools.

## 7. What Phase 2 explicitly does not build

No Tool Gateway and no real tools. No Orchestrator or planning. No Finance
department beyond the single Commentary Agent. No sandbox. No console beyond what
already exists. No external integrations. No API surface beyond the health routes
Phase 1 shipped.

Each is a later phase in `ARCHITECTURE.md` §37's order, and every one of them is
easier to build correctly once an agent demonstrably runs and is recorded.
