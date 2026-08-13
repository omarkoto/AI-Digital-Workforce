# TECHNOLOGY-DECISIONS.md — Foundational Technology Analysis

Analysis and recommendations for the four architectural decisions that block implementation, plus the
one product decision the worked example exposed.

**Status: ACCEPTED 2026-08-12.** All five recommendations — D, E, M, N, and A — were accepted and are
recorded in `docs/DECISIONS.md` as D16, D17, D18, D19, and D22. `docs/ARCHITECTURE.md` has been amended
accordingly. This document is retained as the reasoning behind those decisions, not as a live proposal.

**Covered:** D (backend language/framework) · E (orchestration mechanism) · M (tenant isolation
mechanism) · N (database engine) · A (spreadsheet.write in MVP).

**Deferred, with phase assignments:** B, C, F, G, H, I, J, K, L, O — §8.

---

## 1. How these recommendations were made

**Optimizing for, in order:** correctness of the invariants in `ARCHITECTURE.md` §3 · a small team
shipping an MVP · testability without infrastructure (`CLAUDE.md` §6) · reversibility where it is
cheap · operational surface area small enough to run without a platform team.

**Not optimizing for:** peak throughput, headcount scaling, or what is currently fashionable. At
`PRODUCT.md` §15's MVP scale — 5–20 tenants, 100 concurrent executions platform-wide — no mainstream
technology choice here fails on performance. Choosing as if it might is the most common way small
teams lose a quarter.

**One caveat that outranks everything below.** I do not know the team's existing language expertise.
For decision D in particular, **a team already strong in a language will out-deliver the same team
learning a "better" one**, and that consideration legitimately overrides the ecosystem argument in
§2. Read D's recommendation as conditional on that.

**Not verified.** No code was run and no library was installed. Library-level claims below are
candidates that warrant a short spike, not measured facts, and they are flagged where it matters.

---

## 2. Decision D — Backend language and framework

### 2.1 Options

| Option | Shape |
|---|---|
| **D-1 · Python 3.12 + FastAPI** | Async web framework, Pydantic for validation, SQLAlchemy + Alembic |
| **D-2 · TypeScript/Node + NestJS or Fastify** | Same language as the frontend, Zod for validation, Prisma or Drizzle |
| **D-3 · C# / .NET 8 + ASP.NET Core** | Strong static typing, EF Core, first-class background services |
| **D-4 · Go** | Small language, single binary, strong concurrency primitives |
| **D-5 · Split stack** | Typed core (any of the above) + Python workers for tools only |

### 2.2 Advantages

**D-1 Python.** Owns the MVP tool set outright — the entire tool list in `PRODUCT.md` §11 is
spreadsheet, tabular, chart, and document work, which is Python's home ground. Pydantic gives
*runtime-validated* schemas, which is precisely what the Tool Gateway needs for input and output
validation (`ARCHITECTURE.md` §13) — that is a security control, not a convenience. Largest LLM
ecosystem. Small, readable surface for a small team. SQLAlchemy 2.x plus Alembic is mature, and
PostgreSQL RLS is well-trodden from Python.

**D-2 TypeScript.** One language across frontend and backend — real savings for a small team.
Excellent structural typing for domain modelling. Strong async model that suits I/O-bound
orchestration. Large hiring pool.

**D-3 C#.** The strongest static type system of the five for modelling state machines and domain
invariants. Excellent tooling and debugging. First-class hosted background services, which maps
cleanly onto our worker pool. Native fit for a Windows-based team (`CLAUDE.md` §11). SQL Server RLS
available if N goes that way.

**D-4 Go.** Simplest operational story — one static binary. Excellent concurrency. Fast, predictable,
low memory.

**D-5 Split stack.** Each layer uses the right tool: a strongly-typed core for gates, permissions, and
state machines; Python for data processing. Aligns with the Tool Gateway boundary (B5/B6), which
already isolates tools from the core, and it is the natural path to out-of-process sandboxed tools
later.

### 2.3 Disadvantages

**D-1 Python.** Static typing is optional and advisory; without `mypy --strict` enforced in CI the
domain model degrades quietly. The GIL constrains CPU-bound concurrency — relevant for spreadsheet
work, though process-based workers resolve it. Packaging and dependency management are weaker than the
alternatives. Async discipline is easy to get wrong.

**D-2 TypeScript.** **The tool ecosystem is the problem.** Writing `.xlsx` with embedded native charts
and generating PDFs are materially weaker in Node than in Python — which directly affects decision A
and two of the six MVP tools. Types are erased at runtime, so every trust boundary needs explicit
runtime validation anyway. CPU-bound work is poor.

**D-3 C#.** Smallest agent/LLM ecosystem of the five, though a single provider behind a port is just
HTTP and this matters less than it appears. Spreadsheet and charting libraries are more limited or
commercial. Heavier ceremony slows early iteration.

**D-4 Go.** Verbose for a domain this rich in entities and state transitions. Weakest data-processing
and document-generation ecosystem of the five — a poor match for the MVP tool set. Fewer ergonomics for
the schema-validation work the Tool Gateway needs.

**D-5 Split stack.** Doubles the operational surface at MVP: two toolchains, two dependency sets, two
CI paths, two deployment artifacts, and a cross-process protocol to design and version. For a small
team pre-product-market-fit this is a significant tax paid before it earns anything.

### 2.4 Security implications

The security-relevant question is **not** which language is "safer" — it is which makes the trust
boundaries in `ARCHITECTURE.md` §30 easiest to enforce correctly.

- **Runtime schema validation at boundaries B2, B5, and B6 is a security control.** Pydantic (D-1) and
  Zod (D-2) make this idiomatic. C# and Go need explicit validation code, which is fine but must be
  disciplined. This modestly favours D-1 and D-2.
- **Memory safety:** all five are memory-safe. Not a differentiator.
- **Dependency surface:** Python and Node have the largest transitive dependency trees and therefore
  the largest supply-chain surface. Go and .NET are materially leaner. This is a real point against
  D-1 and D-2, mitigated by lockfiles, pinning, and dependency scanning in CI.
- **Sandboxing later:** D-5 is the strongest, because tools already run out-of-process. D-1 is next
  best, because the eventual Python sandbox and the tool layer share a language.
- **Secret handling:** equivalent across all five. Determined by architecture, not language.

No option is disqualified on security. The differences are in how much discipline each requires.

### 2.5 Development complexity

| Option | For a small team |
|---|---|
| D-1 Python | **Low.** Least code to express the tools. Highest discipline needed on typing. |
| D-2 TypeScript | **Low–Medium.** One language across the stack, but tool implementations get harder. |
| D-3 C# | **Medium.** More ceremony, more safety, slower start, fewer surprises later. |
| D-4 Go | **Medium–High.** Simple language, verbose domain code, hardest tool layer. |
| D-5 Split | **High.** Two of everything before the first feature ships. |

### 2.6 Operational complexity

| Option | Notes |
|---|---|
| D-4 Go | **Lowest** — single binary |
| D-3 C# | **Low** — self-contained deployment, strong runtime diagnostics |
| D-2 TypeScript | **Low–Medium** — mature containerization, noisy dependency management |
| D-1 Python | **Medium** — dependency and native-extension management is the weak point, especially on Windows |
| D-5 Split | **Highest** — two runtimes, two pipelines, one protocol between them |

### 2.7 Fit with our architecture

The architecture is unusually agnostic here by design: the Orchestrator is a persisted state machine,
the LLM sits behind a port, tools sit behind a gateway, and state lives in PostgreSQL. None of that
prefers a language.

Two things do:

1. **The MVP tool set is entirely data and document processing.** Six tools, all of them spreadsheet,
   tabular, chart, or PDF work. This is the single strongest signal in the whole decision, and it
   points at Python.
2. **The Tool Gateway needs declarative input/output schemas with runtime enforcement.** Pydantic and
   Zod model this natively.

Working against Python: the domain layer is dense with state machines and invariants, which is exactly
where static typing pays. This is a genuine tension, and `mypy --strict` in CI is the mitigation rather
than a full answer.

### 2.8 Recommendation

**D-1 — Python 3.12 with FastAPI, Pydantic v2, SQLAlchemy 2.x, and Alembic.**

**Conditional on team expertise.** If the team is already strong in TypeScript or C# and weak in
Python, take D-2 or D-3 instead and accept the tool-layer cost — that trade is usually worth it. If
the team has no strong existing preference, take D-1.

**Mandatory conditions if D-1 is accepted:**

- `mypy --strict` enforced in CI, failing the build. Without this the domain model degrades and the
  main argument against Python becomes true.
- Pydantic models at every trust boundary — API input, tool input, tool output, LLM output.
- Process-based workers, not thread-based, so the GIL never constrains tool execution.
- Dependency pinning with a lockfile plus vulnerability scanning in CI.

### 2.9 Why

The decisive factor is that **the MVP is mostly a data-processing product wearing an orchestration
platform's clothes.** Six of the components in `ARCHITECTURE.md` are generic infrastructure that any
language handles well; the six *tools* are where the actual work happens, and they are spreadsheet,
tabular, chart, and PDF operations. Choosing a stack that makes the generic parts marginally nicer
while making the specific parts materially harder is the wrong trade.

Pydantic is the second reason and it is more than ergonomics: the Tool Gateway's schema validation is
a security control at boundary B5, and a language where that is idiomatic is a language where it is
more likely to be done consistently.

D-5 is the technically ideal end state and the wrong MVP choice. It becomes right when tools need real
sandboxing — which `PRODUCT.md` §11 explicitly defers past MVP. Starting single-language and splitting
later is cheap, because the Tool Gateway boundary already exists in the design; starting split is
expensive and cannot be undone for free.

---

## 3. Decision E — Orchestration mechanism

### 3.1 Options

| Option | Shape |
|---|---|
| **E-1 · Database state machine + queue** | Explicit states in our schema; workers consume queue messages; transitions are transactional |
| **E-2 · Durable workflow engine (Temporal)** | Workflow code with durable execution, built-in timers, retries, and versioning |
| **E-3 · Event sourcing** | Append-only event log as source of truth; state derived by projection |
| **E-4 · Managed cloud workflows** | AWS Step Functions, Azure Durable Functions |

### 3.2 Advantages

**E-1.** Execution state is ordinary queryable data in our own database — which the console's eight
questions read directly, with no projection layer. Satisfies invariant I1 literally. Fully testable
with no infrastructure beyond a database, which `CLAUDE.md` §6 requires. One source of truth. Every
developer already understands it. No new operational component.

**E-2.** Durable execution, timers, retries, and workflow versioning are solved and battle-tested. Long
waits — including the 72-hour approval SLA — are native. Strong observability of workflow history.
Scales well past our horizon.

**E-3.** The best theoretical fit for an audit-centric product: an append-only event log is
conceptually what `CLAUDE.md` §1 describes, and the audit chain (D14) is already event-shaped.

**E-4.** Least infrastructure to operate; the cloud provider runs it.

### 3.3 Disadvantages

**E-1.** We build the parts an engine would give us: timers, retry with backoff, idempotency, and
concurrency limits. Long-running orchestration logic must be written as resumable steps rather than
straight-line code, which is less natural to read.

**E-2.** **Workflow state lives in Temporal's own datastore, not ours.** Our product requires that
state to be first-class, tenant-scoped, RLS-protected, queryable data — so we would project it back
out and maintain two records of the same truth. That is not a small cost; it is a second consistency
problem in the one part of the system that must never be inconsistent. It also adds a cluster plus its
own database to operate, and a substantial new concept for a small team.

**E-3.** Highest conceptual and implementation cost. Projections are a discipline of their own.
Debugging is harder. Realistically out of reach for a small team's MVP.

**E-4.** Directly conflicts with `DECISIONS.md` D3, which requires cloud-specific implementation to
stay behind infrastructure boundaries — an orchestration engine is not a boundary, it is the spine.
Workflow state again lives outside our database. Strong lock-in on the component that is hardest to
replace.

### 3.4 Security implications

- **E-1** keeps all state inside one database, so tenant isolation (M) covers it with the same
  mechanism as everything else. **This is a significant and under-appreciated advantage.**
- **E-2** and **E-4** place execution state in a second system that must independently enforce tenant
  isolation, encryption, and retention. That is a second copy of tenant data, a second crypto-shredding
  surface for D1, and a second audit boundary.
- **E-3** is neutral on isolation but increases the chance of subtle bugs in a security-critical path.

E-1 wins clearly on security, because it does not create a second home for tenant data.

### 3.5 Development complexity

**E-1: Medium.** Straightforward concepts, but we implement timers, retries, and idempotency ourselves.
Estimate a meaningful slice of the first phase.
**E-2: Medium–High.** The engine is easy; the projection layer and the dual-state-management discipline
are not.
**E-3: High.**
**E-4: Medium**, plus vendor-specific tooling that does not transfer.

### 3.6 Operational complexity

**E-1: Lowest** — no new component beyond what we already run. With PostgreSQL (§5), the queue itself
can be `SELECT … FOR UPDATE SKIP LOCKED`, removing the message broker entirely at MVP scale.
**E-2: High** — a Temporal cluster plus its datastore, upgrades, and its own monitoring.
**E-3: Low** infrastructure, high cognitive.
**E-4: Low** infrastructure, high lock-in.

### 3.7 Fit with our architecture

`ARCHITECTURE.md` invariant I1 says all execution state lives in the database. E-1 satisfies it by
construction; E-2 and E-4 satisfy it only through a projection they force us to build and keep correct.

It is also worth being honest about how complex our workflow actually is: six tasks, largely
sequential, with gates, a bounded three-attempt rework loop, and one long human wait. That is not a
workflow-engine-shaped problem. The genuinely hard part — surviving a 72-hour pause — is solved by a
scheduler plus a queue, which we need anyway.

### 3.8 Recommendation

**E-1 — database-driven state machine with a queue.**

With these conditions:

- Every state transition is a database transaction that also writes the audit record, so a transition
  and its audit entry can never diverge.
- Handlers are idempotent, keyed on `{task, attempt, step}` — this is also the groundwork for open
  decision G.
- A single scheduler role converts time into queue messages: SLA expiry, budget windows, retention
  sweeps.
- Per-tenant concurrency limits so one tenant's close week cannot starve another (`PRODUCT.md` §15).

### 3.9 Why

The product requires execution state to be first-class data in our own tenant-isolated database. A
workflow engine wants to own that state. Every path that reconciles those two positions costs more than
building the state machine ourselves — and the reconciliation lands squarely in the audit trail, which
is the one part of the system that must never have two versions of the truth.

Our orchestration is also genuinely simple. Adopting Temporal here would be buying a solution to
problems of scale and complexity we do not have, at the cost of an operational component a small team
must carry from day one.

The migration path is real if we outgrow this: because states and transitions are explicit and
persisted, moving to a durable engine later is a rewrite of the driver, not of the domain. Starting
with an engine and moving away from it is much harder.

---

## 4. Decision M — Tenant isolation mechanism

`DECISIONS.md` D15 fixes the requirement: database-level enforcement, fail closed. Only the mechanism
is open. Note that D15 also explicitly rules out application-layer filtering, so **M-4 below is listed
only to be rejected**.

### 4.1 Options

| Option | Shape |
|---|---|
| **M-1 · Shared schema + row-level security** | One schema; `tenant_id` on every tenant-owned row; RLS policies enforced by the database |
| **M-2 · Schema per tenant** | One schema per tenant in a shared database |
| **M-3 · Database per tenant** | Physically separate database per tenant |
| **M-4 · Application-layer filtering** | `WHERE tenant_id = ?` in application code — **prohibited by D15** |

### 4.2 Advantages

**M-1.** Enforcement lives in the database, exactly as D15 requires: a missing predicate in application
code cannot leak data because the database applies the policy regardless. One migration set. Cheapest
to operate. Scales to thousands of tenants. Straightforward connection pooling. Cross-tenant platform
queries remain possible through an explicit, audited break-glass role.

**M-2.** Intuitive blast-radius story that enterprise buyers understand. Per-tenant export and backup
are simple. Some noisy-neighbour isolation at the storage level.

**M-3.** Strongest isolation. Cleanest answers for residency, per-tenant encryption, and crypto-shredding
under D1. Trivially satisfies the most demanding procurement questionnaires.

### 4.3 Disadvantages

**M-1.** Correctness depends on tenant context being set on **every** connection, in **every** path —
including workers, queue consumers, and scheduled jobs, which have no user session. This is the single
most likely source of a serious bug in this system. Requires care with connection pooling: context must
be set per transaction, not per session. One malformed policy affects all tenants. Requires the
application database role to be non-superuser with `BYPASSRLS` withheld.

**M-2.** Migrations must run across N schemas, and a partial failure leaves tenants on different
versions. Connection and `search_path` management becomes stateful and error-prone. Degrades past a few
hundred tenants. **Critically: schema separation alone is not database-*enforced* isolation** unless
per-tenant roles are also correct — so it often ends up weaker than M-1 while feeling stronger.

**M-3.** Heavy operations for 5–20 pilot tenants. Expensive. Cross-tenant platform operations, metrics,
and migrations become genuinely hard. Overwhelming for a small team at MVP.

### 4.4 Security implications

- **M-1** with `FORCE ROW LEVEL SECURITY` and a non-superuser application role gives true database
  enforcement. The residual risk is entirely about tenant-context propagation — a known, testable,
  single-point risk rather than a diffuse one.
- **M-2**'s security depends on role configuration that teams frequently get wrong; the physical
  separation creates false confidence.
- **M-3** has the smallest attack surface and the highest operational error surface.
- **M-4** makes every missing `WHERE` clause a breach. Prohibited.

The residual risk in M-1 is concentrated and testable, which is exactly what `PRODUCT.md` §14's
permanent adversarial test suite is designed to attack.

### 4.5 Development complexity

**M-1: Low–Medium.** Policies are written once per table and follow a pattern. The real work is a
single disciplined mechanism for setting tenant context, applied everywhere, and the tests that prove
it holds.
**M-2: Medium–High** — multi-schema migration tooling is a project in itself.
**M-3: Medium** application-side, **High** infrastructure-side.

### 4.6 Operational complexity

**M-1: Lowest.** One database, one migration run, one backup.
**M-2: Medium–High.** N migration runs, N failure modes.
**M-3: Highest.** N databases to provision, migrate, back up, monitor, and upgrade.

### 4.7 Fit with our architecture

`ARCHITECTURE.md` §24 already names tenant-context propagation into queue messages and workers as the
most common source of isolation bugs. M-1 concentrates that risk into one mechanism that can be
implemented once and tested adversarially. M-2 and M-3 spread it across connection routing and
provisioning instead — different risk, not less.

M-1 also composes correctly with D1's per-tenant encryption keys: isolation comes from RLS, erasure
comes from key destruction, and the two are independent. Nothing about M-1 forecloses M-3 later for a
specific customer who demands a dedicated database, because the schema is identical.

### 4.8 Recommendation

**M-1 — shared schema with PostgreSQL row-level security.**

Non-negotiable conditions:

- `ENABLE ROW LEVEL SECURITY` **and** `FORCE ROW LEVEL SECURITY` on every tenant-owned table.
- The application database role is not a superuser, is not the table owner, and does not hold
  `BYPASSRLS`.
- Tenant context is set **per transaction**, never per session, because of connection pooling.
- Every queue message carries tenant identity, and worker handlers establish context before any query.
- Absent or ambiguous tenant context denies, never defaults.
- The adversarial isolation suite from `PRODUCT.md` §14 runs permanently in CI and attempts cross-tenant
  access through every route, including workers and scheduled jobs.

### 4.9 Why

It is the only option that satisfies D15 literally, at a cost a small team can carry. M-2 feels safer
than it is and costs more to operate. M-3 is genuinely safer and is the right answer for a specific
regulated customer later, but choosing it for 5–20 pilot tenants would spend most of the team's
operational budget on the wrong problem.

The honest framing: M-1's residual risk is real and specific — tenant context propagation into
asynchronous work. That is far better than a diffuse risk, because a specific risk can be tested. Make
that test suite a first-phase deliverable, not a later one.

---

## 5. Decision N — Database engine

### 5.1 Options

| Option | Shape |
|---|---|
| **N-1 · PostgreSQL 16+** | Open source, RLS, JSONB, partitioning, managed on every cloud |
| **N-2 · SQL Server 2022** | Commercial, RLS, excellent Windows tooling |
| **N-3 · MySQL / MariaDB** | Open source, widely deployed |
| **N-4 · MongoDB** | Document store |

### 5.2 Advantages

**N-1.** Mature row-level security — the mechanism M-1 depends on. JSONB fits evidence payloads and
pinned definition snapshots without forcing premature schema decisions. Declarative partitioning
handles the growth in `PRODUCT.md` §15, where a single execution can produce 10,000 evidence records.
`SELECT … FOR UPDATE SKIP LOCKED` gives a competent queue with no broker. Strong transactional
guarantees, which the audit chain requires. Available managed on every major cloud, preserving D3's
provider flexibility. No licensing cost.

**N-2.** Row-level security is available and mature. Best-in-class tooling and debugging, and a natural
fit for a Windows-based team (`CLAUDE.md` §11). Strong enterprise operational story.

**N-3.** Ubiquitous, familiar, cheap to host.

**N-4.** Flexible schema; good for heterogeneous payloads.

### 5.3 Disadvantages

**N-1.** Connection-heavy workloads need pooling attention. Fewer Windows-native tooling niceties than
SQL Server. Upgrade discipline needed for major versions.

**N-2.** Licensing cost, which is real for a pre-revenue MVP. Weaker JSON ergonomics than JSONB. Less
common in cloud-native SaaS, so fewer patterns to copy. Some cloud-portability friction against D3.

**N-3.** **No true row-level security.** The usual workarounds — views with definer semantics,
per-tenant database users — are not equivalent to enforced RLS, so N-3 cannot satisfy D15 with M-1.
This is disqualifying rather than merely unattractive.

**N-4.** No row-level security. Weaker multi-document transactional guarantees. Our domain is strongly
relational — Execution → Task → Action → Evidence, with versioned definitions and pinning — so a
document store fights the model. The audit chain wants strict ordering and transactional writes.
Disqualified on fit and on D15.

### 5.4 Security implications

The decisive point: **D15 requires database-enforced isolation, and RLS is the mature mechanism for
it.** That reduces the field to N-1 and N-2 immediately.

Both support encryption at rest and integrate with external key management for D1. Both have strong
audit and role separation. Neither has a meaningful security advantage over the other for our purposes.

### 5.5 Development complexity

**N-1: Low.** SQLAlchemy and Alembic are mature; RLS patterns are well documented; testcontainers make
integration testing straightforward.
**N-2: Low** if the team is already .NET/Windows-oriented, **Medium** otherwise.
**N-3 / N-4:** not applicable — they cannot meet the requirement.

### 5.6 Operational complexity

**N-1: Low.** Managed offerings everywhere; well-understood backup, restore, and point-in-time recovery.
Using it as the queue as well removes an entire component.
**N-2: Low–Medium**, plus licensing management.

### 5.7 Fit with our architecture

PostgreSQL fits four distinct needs at once, which is the strongest argument for it:

1. **RLS** implements M-1 and therefore D15.
2. **JSONB** stores evidence payloads and pinned definition snapshots without premature schema
   commitments — useful given that table design is deliberately deferred.
3. **`SKIP LOCKED`** implements the queue for E-1, removing the message broker from the MVP entirely.
4. **Partitioning** handles evidence and audit growth without re-architecture.

That consolidation matters more than any individual feature: it is one component to run instead of
three.

### 5.8 Recommendation

**N-1 — PostgreSQL 16 or later.**

Take **N-2 (SQL Server)** instead only if the organization is already committed to Microsoft
infrastructure and licensing, in which case it is a legitimate choice that also satisfies D15 — but it
does not bring the queue and JSONB consolidation.

### 5.9 Why

D15 makes database-enforced isolation mandatory, which effectively selects PostgreSQL or SQL Server.
Between them, PostgreSQL wins on cost, on cloud portability under D3, and — most importantly — on being
able to serve as database, queue, and evidence store at MVP scale. For a small team, removing an entire
piece of infrastructure is worth more than any feature comparison.

---

## 6. Decision A — Should `spreadsheet.write` be in the MVP tool set?

This is a **product decision**, not an architectural one. It needs your sign-off and a `PRODUCT.md`
§11 amendment; I am recommending, not deciding.

### 6.1 The question

`PRODUCT.md` §11 fixes the MVP tool set as spreadsheet read, tabular transform, tabular compute, chart
render, document render, and artifact read/write. The worked example in `ARCHITECTURE.md` §6 asks the
platform to "update the workbook," which no listed tool can do.

### 6.2 What it is not

Adding it does **not** breach the read-only rule. `PRODUCT.md` §12 prohibits agents writing to *external
business systems*. Producing a new workbook inside the platform, stored as a versioned artifact the user
downloads, is artifact production — which is exactly what the MVP is for. No external system is touched.

### 6.3 Arguments for

- "Give me the analysis in Excel" is the single most natural finance expectation; a PDF plus a separate
  chart file is a visibly weaker deliverable.
- It exercises the artifact versioning model more meaningfully than any other MVP tool.
- The output is deterministically checkable — a generated workbook can be validated against the dataset
  it came from, which suits the gate model.

### 6.4 Arguments against, and one real technical trap

- It expands a tool set that `PRODUCT.md` §11 deliberately fixed. Scope discipline has value in itself.
- **The trap: fidelity-preserving round-trip editing of an uploaded workbook is much harder than it
  looks.** Open-source Python spreadsheet libraries are widely reported to lose charts, images, pivot
  tables, conditional formatting, and macros when reading and re-saving a complex workbook. Silently
  corrupting a controller's workbook would damage trust more than not offering the feature.
  *I have not verified current library behaviour — this warrants a short spike before committing.*
- It widens the redaction surface under D12: workbooks carry hidden sheets, comments, defined names, and
  document metadata that can contain sensitive content.
- It implies a new gate — "is the produced workbook structurally valid and consistent with its source
  dataset?" — which is work not currently in the plan.

### 6.5 Recommendation

**Yes — but scoped to generating a new workbook, not editing the uploaded one.**

Specifically:

- **Include** a `spreadsheet.write` tool that **composes a new workbook artifact from structured data** —
  the variance table, supporting sheets, and native charts, built from `dataset.normalized`.
- **Exclude** in-place modification of an uploaded workbook from MVP. The uploaded file stays pristine as
  its own artifact.
- **Add** a deterministic artifact-integrity gate: the produced workbook opens, has the expected sheets
  and row counts, and its figures reconcile to the source dataset.

In the worked example, task T5 changes from *"produce `march-actuals.xlsx` v2"* to *"produce
`march-variance-pack.xlsx` v1"*, a new artifact derived from the normalized dataset.

### 6.6 Why

This delivers the user-visible value — an Excel file containing the analysis and charts — while
avoiding the round-trip corruption trap entirely. Generating a workbook from known-good structured data
is a well-bounded, deterministic, testable operation. Modifying an arbitrary uploaded workbook while
preserving everything it already contains is an open-ended fidelity problem that could consume a
disproportionate share of the MVP and still disappoint.

It is also more honest about provenance: a generated artifact clearly derives from the validated
dataset, whereas an edited upload blurs the line between what the user supplied and what the platform
produced — a distinction the audit record should keep sharp.

**If you want true in-place workbook editing**, it should be a post-MVP capability with its own spike,
its own fidelity test suite, and its own gate.

---

## 7. Two decisions that must move into Phase 1

You asked about D, E, M, N. Working through them surfaced that **two decisions currently listed as
deferred cannot in fact be deferred**, because both are among the hardest to reverse in the entire
system (`DECISIONS.md` D14, `ARCHITECTURE.md` §3).

| ID | Decision | Why it cannot wait |
|---|---|---|
| **K** | Audit chain scope — per-tenant, global, or per-tenant anchored into global | The chain starts at the first audit record. History written before the scope is settled cannot be re-chained, and the choice interacts directly with M-1: a global chain structurally spans tenants, in tension with the isolation guarantee. |
| **L** | Trusted timestamp source and clock-skew handling | Timestamps *are* evidence. Records written under an untrusted or skewed clock are permanently unreliable, and ordering within the chain depends on it. |

I have not resolved these — they need their own analysis. But they belong in the Phase 1 decision set
alongside D, E, M, and N, not in a later phase. This is a correction to `ARCHITECTURE.md` §37's implied
sequencing.

---

## 8. Phase assignment for the remaining open decisions

Phases follow `ARCHITECTURE.md` §37.

| ID | Decision | Phase | Note |
|---|---|---|---|
| **I** | Evidence inline-vs-blob threshold | **Phase 1** — Execution Record core | Low stakes; start with a constant and tune. Needed because the Evidence Recorder is core. |
| **O** | Queue technology; scheduler as process or role | **Phase 1** | If N-1 is accepted, `SKIP LOCKED` defers a broker entirely. Revisit only if throughput demands it. |
| **F** | Where definitions and skills live — versioned files or database records | **Phase 2** — LLM Port and first real agent | Phase 1 needs only enough to pin stub definitions; the authoring question becomes real when actual skill content arrives. |
| **G** | Idempotency strategy for tool calls | **Phase 3** — Tool Gateway | Design it with the gateway. It becomes safety-critical, not merely correct, at the first external write post-MVP. |
| **H** | Gate evaluators in-process or isolated service | **Phase 4** — Gate Engine | In-process is almost certainly right for MVP; isolation becomes attractive when tenant-authored departments arrive post-MVP. |
| **J** | Does human rejection consume the 3-attempt rework budget? | **Phase 5** — Approval Service | Cannot arise before human gates exist. |
| **B** | Frontend framework and build tooling | **Phase 6** — Console | Phases 1–5 need only a debug view. |
| **C** | Live-update transport — SSE, WebSocket, or polling | **Phase 6**, decided with B | Has API-side implications, so decide both together at the start of Phase 6. |

---

## 9. Proposed MVP technology stack

Contingent on acceptance of D-1, E-1, M-1, and N-1.

### 9.1 Core

| Layer | Choice | Rationale |
|---|---|---|
| Language | **Python 3.12** | Tool ecosystem; `mypy --strict` mandatory in CI |
| API framework | **FastAPI** | Small, async, OpenAPI by default |
| Validation | **Pydantic v2** | Runtime schemas at every trust boundary — a security control |
| Database | **PostgreSQL 16** | RLS, JSONB, partitioning, queue |
| Data access | **SQLAlchemy 2.x** | Mature, explicit, works cleanly with RLS |
| Migrations | **Alembic** | Single migration set under M-1 |
| Queue | **PostgreSQL `SKIP LOCKED`** | No broker at MVP scale; revisit under load |
| Scheduler | Leader-elected worker role via advisory locks | No extra process |
| Object storage | S3-compatible API **behind a port** | Provider deferred per D3 |
| Secrets | External secret store **behind a port** | Never in application configuration |
| Identity | **OIDC** | Per `PRODUCT.md` §20 |

### 9.2 MVP tools

Candidates requiring a short spike before commitment. Not verified.

| Tool | Candidate | Note |
|---|---|---|
| `spreadsheet.read` | openpyxl | Well established for `.xlsx` |
| `spreadsheet.write` | openpyxl | Supports native chart creation; scoped to **new** workbooks per §6.5 |
| `tabular.transform` / `tabular.compute` | pandas or polars | polars if determinism and memory matter more than familiarity |
| `chart.render` | matplotlib | SVG and PNG output; must be configured to `DESIGN.md` §17 |
| `document.render` | **Needs a spike** | HTML→PDF gives the best typographic control but adds a rendering engine; WeasyPrint has known dependency friction on Windows (`CLAUDE.md` §11); ReportLab is pure-Python but lower level. **Flag as a genuine unknown.** |

### 9.3 Quality and operations

| Concern | Choice |
|---|---|
| Testing | pytest · testcontainers for real PostgreSQL · property-based tests for state machines |
| Type checking | `mypy --strict`, failing the build |
| Security | dependency scanning · the adversarial tenant-isolation suite from `PRODUCT.md` §14 |
| Observability | OpenTelemetry traces and metrics · structured logging — **separate from the audit store**, per `ARCHITECTURE.md` §29 |
| Frontend | Deferred to Phase 6 (decisions B and C) |

### 9.4 What this stack deliberately does not include

No message broker. No workflow engine. No cache. No search index. No container orchestrator beyond what
hosting requires. No frontend framework yet.

**Three processes and two infrastructure dependencies.** Every one of those absences is a component a
small team does not have to run, monitor, secure, back up, or upgrade — and each can be added later
when something concrete demands it.

---

## 10. Summary of recommendations

| ID | Recommendation | Confidence | Outcome |
|---|---|---|---|
| **D** | Python 3.12 + FastAPI — **conditional on team expertise** | Medium; the tool ecosystem is decisive, existing skills legitimately override | **Accepted → D16** |
| **E** | Database state machine + queue | High | **Accepted → D17** |
| **M** | Shared schema + PostgreSQL RLS | High | **Accepted → D18** |
| **N** | PostgreSQL 16+ | High; D15 nearly forces it | **Accepted → D19** |
| **A** | Add `spreadsheet.write`, scoped to generating new workbooks only | High on the scoping; the yes/no is yours | **Accepted → D22** |

All five accepted 2026-08-12. `ARCHITECTURE.md` open decisions A, D, E, M, N, and O are closed;
`PRODUCT.md` §11 and §8.3 remain **stale pending amendment** for A.

**Analysed separately and now also resolved:** K → D20 and L → D21, in `docs/PHASE-1-DECISIONS.md`.

**The mandatory conditions attached to D16 stand as accepted:** `mypy --strict` failing the build,
Pydantic at every trust boundary, process-based workers, and dependency locking with vulnerability
scanning. The PDF rendering library remains an open spike.
