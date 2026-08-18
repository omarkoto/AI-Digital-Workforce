# Phase 3 Implementation Plan — The Tool Gateway

**Goal.** Let an agent do something to the world, and let exactly one component
decide whether it happens.

**Scope, from `ARCHITECTURE.md` §37.** That section's order puts *"Tool Gateway
with two real tools"* immediately after the LLM Port and one real agent. Phase 3
is that step and only that step. The Gate Engine's remaining Finance gates, the
Approval Service beyond what exists, and the console are §37's later items and
stay out.

**Status.** Plan only. No code until this is approved.

---

## 1. Where Phase 2 left off

Phase 2 built the agent and proved it: 615 tests, `E-1042` driven end to end by a
model-backed agent that writes its own narrative, fails G4, reworks, and passes.

| Built | What Phase 3 does with it |
|---|---|
| LLM Port, fake + Ollama Cloud providers | Unchanged. The gateway is downstream of the model, never inside it |
| Agent Runtime loop | Its tool proposals stop being refused and start being submitted |
| `tool_proposal.detect` | Becomes the parser for a *structured* request instead of a bare name |
| Context assembly, D13 separation | Tool results enter the data region, like every other untrusted input |
| Definition authoring + deprecation | Tool descriptors are a fifth definition kind, on the same machinery |
| Action lifecycle + evidence | The gateway becomes the sole writer of both |
| Cost accounting, budgets | Gains a second metered resource: tool calls per task |
| Artifact versions, gates, rework | Unchanged. A tool produces evidence; an artifact is still the agent's output |

**Nothing in Phase 1 or Phase 2 changes.** The one deliberate behavioural change
is that a *granted* tool proposal now executes instead of being refused — and the
refusal path stays, because an ungranted proposal must still be refused and
recorded exactly as it is today.

## 2. The single structural rule

`ARCHITECTURE.md` §2: **the Agent Runtime proposes, the Tool Gateway disposes.**
I2 has been enforceable for free until now because there was nothing to execute.
Phase 3 is where it becomes a real constraint rather than an absence, and every
decision below is downstream of it.

## 3. What Phase 3 builds

Five components.

### 3.1 Tool Registry (`adw/models/tool.py`, `adw/services/tool_registry.py`)

**What.** Versioned tool descriptors: name, input schema, output schema, timeout,
resource limits, required scopes.

**Why.** A tool the platform cannot describe is a tool it cannot validate, limit,
or authorize. The descriptor is what the gateway checks against.

**Connects to.** The definition machinery already built. Tool versions are
platform-curated (D30), immutable by trigger, pinned per task (I4), and
deprecated through `definition_deprecation` — a fifth link column on the table
added in migration 0009, not a second mechanism.

**Must not.** Hold a secret. Hold a credential. Be writable by `adw_app`.

### 3.2 Permission grants (`adw/models/grant.py`, `adw/services/grant_service.py`)

**What.** A grant of `{task, tool version, scope}` with an expiry, and its
revocation.

**Why.** D10 and I9. This is the component that makes "least privilege" a
mechanism rather than an aspiration, and it is the reason injected content cannot
escalate: instruction and capability live in different tables, so persuading a
model changes nothing about what it may do.

**Connects to.** Task (grants are task-scoped and tenant-scoped), the audit chain
(grant and revocation are both auditable events), the gateway (sole reader).

**Must not.** Be granted by the Agent Runtime, or by anything the model can
influence. Outlive its task. Be checked anywhere except at the invocation site.

**Blocked** on D10's pre-declared-versus-dynamic question — see §6.

### 3.3 Tool Gateway (`adw/services/tool_gateway.py`)

**What.** The single runtime chokepoint. `ARCHITECTURE.md` §13 fixes the order
and it is not negotiable:

1. verify a live, in-scope, unexpired grant for `{task, tool}`
2. validate input against the pinned tool schema
3. Action `planned → attempted`
4. resolve secret *references* internally
5. execute under timeout and resource limits
6. Action `executed`
7. validate output against the schema
8. **redact**, then persist Evidence (I3)
9. Action `succeeded` or `failed`
10. audit event
11. return the result to the runtime **as untrusted data**

**Why.** Everything dangerous — permission, secrets, external contact, limits,
redaction — is concentrated in one reviewable component. That concentration is
the point; spreading any of it is how a platform acquires a second, weaker path.

**Must not.** Decide *what* to call. Interpret business meaning. Return a secret.
Return a result as anything but data. Reach `succeeded` without evidence (I10).

### 3.4 Two real tools (`adw/tools/`)

**Which two, and why:** `spreadsheet.read` and `tabular.compute`.

They are the pair `E-1042` already names in its Phase 1 scenario, so the
deliverable is a scenario that gets *more* real rather than a new one. They need
no chart library, no PDF library (P6 is still an unstarted spike), no external
API, and no sandbox — because they are platform code with parameterized inputs,
not agent-generated code, which is exactly the trade-off `PRODUCT.md` §11 states
and accepts.

**Must not.** Execute anything the model wrote. Read outside the tenant's blob
scope. Return unbounded output — a tool that can return a gigabyte is a denial of
service with extra steps.

### 3.5 Secret Store port (`adw/ports/secrets.py`)

**What.** The interface by which the gateway resolves a secret *reference* to a
value, internally, at step 4.

**Why.** `CLAUDE.md` §4: never expose a secret to an LLM. The model sees a
reference name and nothing else, and the only component that can dereference it
is the one component reviewed for that purpose.

**Honest scoping.** Neither Phase 3 tool needs a credential. The port and the
reference-resolution seam are built anyway, with a dev-only adapter that refuses
outside `dev` — because retrofitting a secret boundary after tools already pass
raw arguments is exactly the change that never gets made.

---

## 4. The deliverable

**`E-1042` again, with the tool calls real.**

Today the Commentary Agent is handed a dataset as a literal. In Phase 3 it asks
for `spreadsheet.read`, the gateway checks a grant and executes it, the result
comes back as fenced untrusted data, and the agent writes its narrative from
figures it actually retrieved. G4 still catches an unsourced figure, rework still
opens, a human still signs, and both chains still verify.

Three additional proofs, each of which must fail loudly if the gateway is wrong:

1. **An ungranted tool is refused**, recorded, and the run continues — the
   behaviour Phase 2 already has, now with a gateway present to say no.
2. **An expired grant is refused**, proving the time-box is real and not
   decorative.
3. **A tool that times out** produces a `failed` Action with evidence, never a
   hung task and never a silent success.

**Definition of done:** the full suite green, no Phase 1 or Phase 2 test modified
to accommodate Phase 3, and the scenario suite still running with **no network
access**.

---

## 5. Sequence

Seven tasks, each independently testable and committable.

| # | Task | Deliverable |
|---|---|---|
| 1 | Tool Registry + descriptors, on the existing definition machinery | A tool version resolves and pins for a task |
| 2 | Permission grants and revocation (**needs D10 resolved**) | A grant is live, scoped, expiring, and audited |
| 3 | Secret Store port + dev adapter | References resolve inside the gateway and nowhere else |
| 4 | Tool Gateway: the eleven steps, with a stub tool | Every step provable in isolation |
| 5 | `spreadsheet.read` | A real file becomes evidence |
| 6 | `tabular.compute` | A computed figure becomes evidence |
| 7 | Runtime integration + `E-1042` with real tool calls | Proposals dispose instead of being refused |

Tasks 1, 3 and 4 can start immediately. Task 2 is blocked; see below.

---

## 6. Genuinely blocking decisions

**B3 — D10: pre-declared or dynamic grants.** D10 leaves this open and
recommends pre-declared with explicit escalation. It blocks task 2, which blocks
tasks 4–7, so it needs deciding first.

The trade-off, stated without recommending: **pre-declared** means the full
permission footprint of an execution is reviewable by a human at plan
confirmation, which is a strong safety property and fits `PRODUCT.md` §18 — but
it needs the Orchestrator, which does not exist and is itself blocked on the
Execution state machine's unresolved transitions. **Dynamic** lets Phase 3
proceed without an Orchestrator, at the cost of no single moment where a person
sees everything an execution may do.

There may be a third answer: grants declared per *task* at task creation, which
`task_service.create_task` already does for definition versions and which needs
no Orchestrator. That is not what D10 describes, so it is a decision to take
rather than one to assume.

**B4 — D10: in-flight revocation.** What happens to a tool call already running
when its task ends, its grant expires, or a budget trips. Phase 3's two tools are
short and idempotent, so a defensible answer is "let it finish, refuse the next
one" — but that answer stops being defensible the moment an external write
arrives, and writing it down now is cheaper than discovering it later.

## 7. Not blocking, but worth knowing

- **Open decision G (idempotency for tool calls)** can be deferred, with a
  reason: `ARCHITECTURE.md` §14 says it becomes critical when external writes
  arrive, and both Phase 3 tools are pure reads and computations. It must be
  resolved before the first tool that writes anywhere.
- **A spreadsheet reader needs a library.** `openpyxl` for XLSX, stdlib `csv` for
  CSV. That is a new runtime dependency and a supply-chain decision, not a
  drive-by import.
- **File ingestion is not in this phase.** `PRODUCT.md` §11's authenticated
  upload is its own component; Phase 3's reader takes a blob reference from the
  existing tenant-scoped BlobStore, which is enough to make the tool real.
- **The proposal format changes shape.** `TOOL_CALL: name` was enough to detect
  an intent that was always refused. A gateway needs arguments, and arguments
  need a schema — so the parser gains structure and a malformed proposal becomes
  a recorded refusal rather than a crash.
- **Tool calls per task (50, `PRODUCT.md` §25)** joins the token budget as a
  metered limit. The cost service already has the shape for it.

## 8. What Phase 3 explicitly does not build

No Orchestrator or planning. No sandbox or agent-generated code. No chart or PDF
rendering. No external API calls or browser automation. No file upload surface.
No console. No department beyond the single Commentary Agent.

Each is a later phase in `ARCHITECTURE.md` §37's order, and each is safer to
build once exactly one component has been proven to be the only thing that can
make a tool run.
