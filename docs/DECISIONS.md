# DECISIONS.md — MVP Decision Record

Resolved product decisions that unblock architecture design. Each entry states the decision, why it
was made, what it affects, what remains open, and how reversible it is.

**Authority.** These decisions are binding for MVP. They resolve open items from `PRODUCT.md` §26 and
formalize principles asserted in `CLAUDE.md`. Where a decision here conflicts with an earlier
document, this record wins and the earlier document is amended to match — deliberately, not silently.

**Scope.** Decisions only. No architecture, no schemas, no implementation. "Remains open" items are
genuinely unresolved and must not be settled by whatever gets built first.

**Status:** D1–D15 accepted 2026-08-10. D16–D26 accepted 2026-08-12.

---

## Reversibility at a glance

Reversibility is judged as *cost to change after the MVP ships*, not cost to change today.

| # | Decision | Reversibility |
|---|---|---|
| D1 | Crypto-shredding for erasure | **Low** |
| D2 | 7-year retention default, tenant-configurable | **High** |
| D3 | Multi-tenant SaaS, single region | **Low** (tenancy) / Medium (region, provider) |
| D4 | No self-review | **High** to relax — but relaxing forfeits the product claim |
| D5 | Platform-curated departments | **High** — opening authorship is additive |
| D6 | Mandatory human final gate | **High** to relax, **Low** to add later |
| D7 | 72-hour approval SLA, expiry never approves | **High** |
| D8 | Single LLM provider behind abstraction | **Medium** |
| D9 | Definition versioning and per-execution pinning | **Low** |
| D10 | Per-execution, time-boxed tool permissions | **Low–Medium** |
| D11 | Maximum 3 rework loops per task | **High** |
| D12 | Redaction before persistence | **Irreversible for data already written** |
| D13 | All external content untrusted | **Not a stance to reverse**; mechanisms evolve |
| D14 | Hash-chained, tamper-evident audit | **Low** |
| D15 | Database-level tenant isolation | **Lowest** |
| D16 | Python 3.12 + FastAPI backend | **Medium** |
| D17 | Database state machine + PostgreSQL queue | **Medium** |
| D18 | Shared schema + PostgreSQL RLS | **Low** |
| D19 | PostgreSQL 16+ | **Low** |
| D20 | Per-tenant audit chains, anchored | **Low** |
| D21 | `transaction_timestamp()`, order from the chain | **Low** for records already written |
| D22 | `spreadsheet.write`, new workbooks only | **High** |
| D23 | RFC 8785 canonical serialization | **Low** |
| D24 | SHA-256 with a recorded algorithm identifier | **Medium** — the identifier is what makes it so |
| D25 | Key identifier stored with ciphertext | **Low** |
| D26 | Cryptographically random external identifiers | **Low** |
| D27 | Dedicated, never-destroyed platform chain key | **Low** |
| D28 | UUIDv7 by default, UUIDv4 for tenant identifiers | **Low** |
| D29 | Raw-byte digests for content; JCS only for platform-built structures | **Low** |

The seven hardest to reverse — D15, D12, D14, D9, D1, D20, D21 — are the ones architecture must get
right on the first attempt. They cluster around identity, integrity, and time, which is what this
product sells.

---

## D1 · Erasure vs immutability — crypto-shredding

**Decision.** Tenant data is encrypted with per-tenant keys. When erasure is required, the key is
destroyed rather than the records. Ciphertext and the audit structure remain in place; the plaintext
becomes permanently unrecoverable. The global audit structure keeps its integrity because the chain
links over hashes and metadata, never over plaintext payloads.

**Why.** `CLAUDE.md` §3 requires artifacts to be append-only and historical versions to remain
auditable. GDPR requires erasure. Deleting records satisfies erasure and destroys the audit
guarantee; keeping records satisfies audit and violates erasure. Key destruction is the only
mechanism that satisfies both: the record of *what happened* survives, the *content* does not.

**Affects.** Key management and KMS design · encryption boundaries across the database, object
storage, search indexes, caches, and backups · audit event structure, which must separate chain
metadata from encrypted payload · backup and restore, where old backups also become unreadable, which
is a feature and not a defect · tenant offboarding · `PRODUCT.md` §14, which already mandates
per-tenant keys for this reason.

**Remains open.**
- **Granularity.** Per-tenant keys erase a whole tenant. GDPR erasure is normally per *data subject*.
  Erasing one employee's data inside a live tenant needs a finer key hierarchy (envelope keys per
  subject or per data category). Unresolved and consequential.
- **Key custody** — platform-held versus customer-managed (BYOK). BYOK is a common enterprise
  requirement and changes the key hierarchy.
- **Metadata residue.** Timestamps, event types, actor IDs, and tenant IDs stay readable by design.
  Whether that residue is itself personal data under GDPR needs legal input.
- **Conflict with legal retention** — see D2.

**Reversibility: Low.** The key hierarchy and encryption boundaries are structural. Retrofitting means
re-encrypting all historical data and restructuring the audit record.

---

## D2 · Retention — 7 years, tenant-configurable

**Decision.** Default retention for financial records is 7 years. Retention is configurable per
tenant. Legal confirmation per jurisdiction remains a business decision and is explicitly not
resolved here.

**Why.** Seven years is the common statutory horizon for financial records across major
jurisdictions, which makes it a defensible default rather than a guess. Configurability is necessary
because the correct value is jurisdictional and customer-specific.

**Affects.** Storage sizing and cost · archival tiering · the erasure mechanism in D1 · audit export
scope · `PRODUCT.md` §15 scale assumptions.

**Remains open.**
- **Legal confirmation** per jurisdiction and per record class. Carried forward from `PRODUCT.md`
  §26 #2.
- **Which wins when retention and erasure conflict.** A statutory retention obligation can override
  an erasure request under GDPR's legal-obligation exemption, but the platform needs an explicit rule
  and an auditable record of which one applied and why.
- **Differentiated retention.** Artifacts, evidence, and audit events may warrant different periods.
  A single uniform value is assumed for now; if that proves wrong, it is schema work, not config.
- **A retention floor.** If a tenant can set 30 days, they can undermine the auditability the product
  sells. A minimum is probably required, and who may set it is unresolved.

**Reversibility: High** for the number, which is configuration. **Medium** for the model, since moving
from uniform to per-class retention is a data-model change.

---

## D3 · Deployment — multi-tenant SaaS, single region

**Decision.** Multi-tenant SaaS. One cloud region for MVP. Cloud-provider-specific implementation
stays behind infrastructure boundaries. On-premise deployment is not designed for in MVP.

**Why.** One codebase and one deployment is the only way to iterate at MVP speed. Infrastructure
boundaries keep two future doors open at low cost: switching provider, and offering single-tenant or
customer-hosted topologies to the regulated buyers who will eventually demand them.

**Affects.** Infrastructure selection · data residency claims · disaster-recovery design · the
compliance answers in `PRODUCT.md` §17 · enterprise sales objections.

**Remains open.**
- **Cloud provider and region.** Carried forward from `PRODUCT.md` §26 #3.
- **What "infrastructure boundary" means concretely** — which capabilities get a port (object storage,
  queue, secret store, KMS, identity) and which may bind directly. A boundary that is not specified
  is a boundary that leaks.
- **Residency tension.** A single region may not satisfy GDPR-sensitive or MENA customers who expect
  in-region storage. This may force a second region earlier than planned.
- **Disaster-recovery region strategy**, which interacts with the RPO/RTO targets still open in
  `PRODUCT.md` §22.

**Reversibility.** Multi-tenancy: **Low** (see D15). Region count: **Medium** — adding a region is
significant but bounded work. Provider: **Medium** if the boundaries hold, **Low** if they leak.

---

## D4 · Self-review — never permitted

**Decision.** The requester of an execution and the producer of an artifact can never approve the
Control Gate covering it. There is no self-review exception in MVP.

**Why.** "Nothing approves itself" is one of the three commitments the product is built on
(`PRODUCT.md` §2). An exception that exists will be used, and it will be used precisely when deadline
pressure is highest — which is exactly when the control matters. An absolute rule is also far cheaper
to enforce and to explain to an auditor than a conditional one.

**Affects.** Role model and separation of duties (`PRODUCT.md` §4) · gate decision authorization ·
approval routing · tenant onboarding, which now requires at least two qualified people · the
integrity warning specified in `DESIGN.md` §11.5.

**Remains open.**
- **Minimum approver pool.** A tenant with a single finance user cannot complete an execution. Do we
  block onboarding, require a designated second approver, or permit an external approver? Unresolved
  and a real go-to-market constraint.
- **Approver unavailability**, which interacts with the SLA in D7.
- **Precise identity resolution for "producer."** Is the producer the agent, the agent's owning
  department, or the human who initiated the execution? The rule must be exact, because it is
  enforced in code.

**Reversibility: High** mechanically — adding an exception later is additive. **Effectively permanent
in practice**, because relaxing it forfeits the claim the product is sold on.

---

## D5 · Department authorship — platform-curated in MVP

**Decision.** MVP departments are platform-curated. Tenant-authored departments are post-MVP.

**Why.** Department content is security-relevant: it declares tool grants, gate rules, and artifact
contracts. Tenant authorship is therefore a privilege-escalation surface, and opening it before the
permission and versioning model is proven would be building the riskiest feature first.

**Affects.** Permission model · department packaging and versioning · support burden · roadmap
sequencing.

**Remains open.**
- **The line between customization and authorship.** `PRODUCT.md` §6 and §26 #16 already assume
  tenants configure policy — materiality thresholds, approver assignment, budgets. Which knobs are
  tenant-controlled and which are curated must be drawn precisely, because the boundary *is* the
  security boundary.
- **Rollout of curated department versions** — whether a tenant can pin a department version, and what
  happens to in-flight executions when a new version ships. Interacts directly with D9.

**Reversibility: High.** Opening authorship later is additive, *provided* versioning (D9) and
per-execution permission scoping (D10) are built now. If they are not, this becomes Low.

---

## D6 · Human approval — mandatory final gate

**Decision.** Every execution ends with a human final gate. No human-optional gates in MVP.

**Why.** Supervised work is the product. It is also the compensating control for the two failure modes
that cannot be fully engineered away: model error and prompt injection (D13). A human at the end is
the backstop that does not depend on the model behaving.

**Affects.** Execution state machine terminal states · notification and the Needs Attention queue ·
end-to-end latency and throughput · the console's approval surfaces.

**Remains open.**
- **Executions that fail or are cancelled before reaching the final gate.** Do they terminate without
  human closure, or does every execution require a human disposition regardless of outcome? Unresolved
  and it changes the state machine.
- **Granularity.** Does one human gate cover a multi-artifact report pack, or does each artifact need
  its own? The Finance MVP produces a composite artifact, which makes this immediate.
- **Re-runs** — whether a re-executed requirement requires fresh approval.

**Reversibility: High** to relax later (configuration). **Low** to add later — retrofitting an
approval workflow onto a system that never had one is invasive.

---

## D7 · Approval SLA — 72 hours, expiry never approves

**Decision.** Human gates carry a default 72-hour SLA. Expiry never means approval. On expiry the
execution moves to Needs Attention and requires explicit human action. Escalation is explicit and
audited.

**Why.** This closes the deadlock gap without introducing a worse failure. An execution that hangs
forever is bad; an execution that auto-approves because nobody looked is catastrophic, and would
directly violate `CLAUDE.md` §3.

**Affects.** Timers and scheduling · notification · the Needs Attention queue · the execution state
machine, which gains an `Expired` state · audit events for expiry and escalation.

**Remains open.**
- **Calendar hours versus business hours.** 72 calendar hours spanning a weekend is roughly one
  business day. Tenant timezone and holiday calendars are unmodelled.
- **Escalation target.** Carried forward from `PRODUCT.md` §26 #7 — manager, department owner, or a
  designated backup approver.
- **Close-week behavior.** `PRODUCT.md` §15 notes load concentrates into the first five business days;
  a 72-hour SLA may be too slow precisely when the work matters most.
- **Whether the SLA clock pauses** while a task is in rework.

**Reversibility: High.** Durations and routing are configuration. The `Expired` state itself is a
state-machine addition — **Medium** if added later.

---

## D8 · LLM provider — one, behind an abstraction

**Decision.** MVP uses a single LLM provider behind a provider abstraction. The provider must support
contractual zero data retention and no training on customer data.

**Why.** The compliance requirement is a hard gate on provider selection, not a preference — the
provider is a subprocessor (`PRODUCT.md` §17), and one that cannot commit contractually is unusable
regardless of model quality. The abstraction satisfies `CLAUDE.md` §6 and, more importantly, keeps
orchestration, gates, permissions, and artifact handling testable with no live model.

**Affects.** Agent runtime · prompt and tool-calling layer · cost model · DPA and subprocessor
disclosure · test strategy.

**Remains open.**
- **Which provider.** Carried forward from `PRODUCT.md` §26 #8.
- **Whether the abstraction is real.** An abstraction validated against exactly one provider is a
  hypothesis. Mitigation is a fake/stub provider used throughout the test suite, which also serves the
  `CLAUDE.md` §6 requirement — but it is not the same as proving portability.
- **Provider-specific capabilities** — tool calling, structured output, prompt caching — and how they
  are exposed without leaking provider concepts into business logic.
- **Outage behavior.** `PRODUCT.md` §22 requires running executions to pause and resume rather than
  fail. Whether a fallback provider is ever permitted is unresolved.
- **Model tiering.** Carried forward from `PRODUCT.md` §26 #9.

**Reversibility: Medium.** Swapping providers is cheap if the abstraction holds, and the abstraction's
quality is only genuinely proven at the second provider.

---

## D9 · Definition versioning and pinning

**Decision.** Agent Definitions, Skills, Artifact Definitions, and Control Gate Definitions are all
versioned. Every execution pins the exact versions it ran against.

**Why.** Without pinning, the audit record cannot answer "what were this agent's instructions,
permissions, and validation rules at the time?" — which defeats the purpose of keeping the record at
all. Pinning also makes reruns comparable and rollbacks safe.

**Affects.** Every definition entity · the execution record · gate evaluation, which must run the
pinned rule rather than the current one · department packaging (D5) · migration strategy.

**Remains open.**
- **Immutability of referenced versions.** A version that an execution pins can never be mutated or
  hard-deleted; only deprecated. This needs stating as a rule, and it constrains the whole
  definition lifecycle.
- **Transitive pinning.** If a Skill references a Tool, does the execution pin the Tool version too?
  Where the pinning graph terminates is unresolved.
- **Mid-flight version changes.** Recommendation is that a running execution never migrates to a newer
  definition version, but this is not yet decided.
- **Tenant policy overrides** — thresholds and approver assignments — need versioning alongside the
  definitions they modify, or the pin is incomplete.

**Reversibility: Low.** Retrofitting is worse than expensive: executions created before pinning
existed can never be pinned retroactively, so the audit gap for that period is permanent.

---

## D10 · Permission model — per-execution, time-boxed grants

**Decision.** Tool permissions are granted per execution and task, time-boxed, and revoked when the
task ends. Skills never grant permissions.

**Why.** Least privilege, and something sharper: separating *instruction* from *capability* is the
structural defense against an agent being talked into capability it should not have. If a Skill could
confer a Tool, then injected content that reaches an agent's instructions could escalate privilege.
Because it cannot, injection can at most misuse what was already granted.

**Affects.** Authorization at every tool invocation site · grant lifecycle and credential lifetime ·
audit, since grants and revocations are themselves auditable events · agent runtime · the permission
display requirements in `DESIGN.md` §9.4.

**Remains open.**
- **In-flight revocation semantics.** What happens to a tool call already running when a task ends or
  a budget trips.
- **Grant lifetime versus long tasks**, and whether refresh is permitted or a task must be re-granted.
- **Pre-declared versus dynamic grants.** Pre-declaring grants in the Execution Plan would let a human
  review the full permission footprint at plan confirmation, which is attractive; dynamic requests are
  more flexible. Recommendation is pre-declared with explicit escalation, but this is not decided.
- **Reconciling grants with downstream service-account scope**, where the underlying integration has
  its own permissions that may exceed the grant.

**Reversibility: Low–Medium.** Grant-based authorization is structural; retrofitting it over static
role checks touches every tool call site.

---

## D11 · Rework — maximum 3 loops per task

**Decision.** A task may enter rework at most 3 times. Exceeding the limit pauses the task and routes
it to Needs Attention.

**Why.** Bounds cost and prevents an unbounded failure loop. More importantly, a task that has failed
its gate three times is not a retry problem — it is a signal that the plan, the definition, or the
input is wrong, and a human should see it.

**Affects.** Task state machine · cost controls (`PRODUCT.md` §25) · Needs Attention queue · the
timeline rendering already specified in `DESIGN.md` §12.1 ("Rework 2 of 3").

**Remains open.**
- **Execution-level aggregate limit.** Thirty tasks at three reworks each is within every per-task
  limit and still expensive. A ceiling on total reworks per execution is probably needed.
- **Per-task or per-gate.** A task facing multiple gates may fail different ones for different reasons.
- **Whether human rejection counts toward the same budget** as deterministic gate failure. They are
  arguably different signals and may warrant separate limits.
- **Tenant configurability** and the bounds within which it is permitted.

**Reversibility: High.** A number in configuration.

---

## D12 · Evidence — redaction before persistence

**Decision.** Secrets and Restricted-class data are redacted **before** evidence and artifacts are
persisted. Render-time redaction is never relied upon.

**Why.** The store is immutable by design. Anything written is written permanently, so hiding a value
at display time leaves it in the store forever and turns the audit store into a credential
repository — the exact opposite of `CLAUDE.md` §4. This reverses what an earlier draft of `DESIGN.md`
implied and is the correct resolution.

**Affects.** Evidence ingest pipeline · tool output handling · artifact write path · application
logging · error payloads · `DESIGN.md` §9.4 and §15.2, which need amending to match.

**Remains open.**
- **Detection is imperfect.** What happens when redaction misses? The backstop is encryption at rest
  plus key destruction (D1), together with a documented incident path — but the residual risk is real
  and permanent, and should be stated to customers rather than hidden.
- **False positives are corrupting.** Over-redacting a genuine financial figure would silently damage
  an artifact and could defeat the G4 traceability gate. The redaction catalogue needs a precision
  target, not just a recall target.
- **Whether redaction is ever reversible under break-glass.** It should not be, but that needs stating.
- **Interaction with G4**, which must verify narrative figures against source values that may
  themselves be sensitive.

**Reversibility: Irreversible for data already written.** The policy is trivial to change; the
consequence of having it wrong is permanent. This is why it is decided now rather than later.

---

## D13 · Prompt injection — all external content is untrusted

**Decision.** All user input, uploaded files, artifact content, web content, and tool output are
untrusted. Untrusted content must never expand permissions, change security policy, bypass a Control
Gate, or override system or agent instructions.

**Why.** This is the primary attack surface of a platform whose agents hold real permissions against
real systems. A spreadsheet cell, a PDF, or an API response is an instruction-shaped payload arriving
inside data, and the system must be built so that it cannot matter.

**Affects.** Prompt construction and instruction/data separation · agent runtime · tool output
handling · permission checks (D10) · gate evaluation (D6) · the threat model that `CLAUDE.md` §4 does
not yet name.

**The structural point.** Deterministic Control Gates are the primary compensating control against
injection, because **an injected instruction cannot persuade a deterministic check to pass**. A
model can be talked into anything; a reconciliation check cannot. This is an independent and strong
reason to prefer deterministic validation wherever it is available, reinforcing `CLAUDE.md` §6 for a
security reason rather than a quality one.

**Remains open.**
- **There is no complete defense.** Specific controls are architectural and unresolved: instruction and
  data separation, structured tool I/O in place of free text, output constraining, allowlisting,
  provenance tagging of content by trust level.
- **Detection and response** — whether a suspected injection attempt is itself an audit event and what
  it triggers.
- **Red-teaming** as a permanent test suite rather than a one-off review.

**Reversibility.** The stance is not something to reverse. The mechanisms will evolve continuously.

---

## D14 · Audit — append-only and hash-chained

**Decision.** Audit events are append-only and tamper-evident through hash chaining. Audit records
cannot be modified through the application.

**Why.** Append-only alone is not tamper-evident. A row that anyone with database access can `UPDATE`
is not an audit trail, and for a product whose thesis is "designed by people who expect to be
audited," that gap is fatal. Chaining makes alteration detectable rather than merely discouraged.

**Affects.** Audit event structure · the write path · verification tooling · export · backup · and the
interaction with D1, where the chain must link over hashes and metadata so that destroying a tenant
key leaves the chain intact.

**Remains open.**
- ~~**Chain scope — global versus per-tenant.**~~ **Resolved by D20** — per-tenant chains anchored into
  an entangled global anchor chain.
- **External anchoring or notarization** — whether chain heads are published somewhere the platform
  operator cannot alter. Without it, an operator with full infrastructure access could rewrite both
  records and chain.
- **Verification cadence and ownership** — who runs verification, how often, and what a failure
  triggers.
- **Retention expiry versus chain integrity.** Deleting expired records breaks the chain. This is a
  second, independent argument for D1's key destruction over deletion: shredding preserves the chain
  where deletion severs it. Expiry should therefore be implemented as key destruction plus tombstones
  that retain hashes, not as row removal.
- ~~**Trusted time**~~ **Resolved by D21** — PostgreSQL `transaction_timestamp()` for event time, with
  authoritative ordering carried by the chain sequence rather than by any clock.

**Reversibility: Low.** History written before chaining existed can never be proven afterwards.

---

## D15 · Tenant isolation — enforced in the database

**Decision.** Every tenant-owned record carries tenant identity. Database-level isolation is mandatory.
Cross-tenant access fails closed.

**Why.** This is the least reversible decision in the entire system. Application-layer filtering means
any single missing `WHERE` clause is a data breach; database-enforced isolation means an application
bug is not sufficient to cross a tenant boundary. Fail-closed ensures that an unknown or ambiguous
tenant context denies rather than leaks.

**Affects.** Every table and every query · connection and session management · background jobs and
async workers · object storage key layout · caches · search indexes · logs · metrics · the adversarial
isolation test suite required by `PRODUCT.md` §14.

**Remains open.**
- **The mechanism** — row-level security, schema-per-tenant, or database-per-tenant. This is an
  architecture decision, deliberately not made here; the *requirement* is what is fixed.
- **Tenant context in asynchronous work.** Background jobs, queue consumers, and scheduled tasks have
  no user session to derive tenant from. This is the most common source of isolation bugs.
- **Caches, search indexes, and derived stores**, which sit outside the database and are the classic
  leak paths. They need explicit treatment or the database guarantee is only partial.
- **Break-glass procedure** — its definition, its two-person authorization, and its audit trail.
- **Platform-level analytics.** Whether cross-tenant aggregation is ever permitted, by whom, and
  through what path.

**Reversibility: Lowest of all fifteen.** Retrofitting touches every query and every audit record
already written.

---

## D16 · Backend language and framework — Python 3.12 + FastAPI

**Decision.** Python 3.12 with FastAPI, Pydantic v2, SQLAlchemy 2.x, and Alembic. `mypy --strict`
enforced in CI and failing the build. Pydantic models at every trust boundary — API input, tool input,
tool output, LLM output. Process-based workers, never thread-based. Dependency lockfile plus
vulnerability scanning in CI.

**Why.** The MVP is a data-processing product wearing an orchestration platform's clothes: all six MVP
tools are spreadsheet, tabular, chart, or document work, which is Python's strongest ground. Pydantic
makes runtime schema validation at boundary B5 idiomatic, and that validation is a security control
rather than a convenience. The alternatives make the generic platform parts marginally nicer while
making the specific tool parts materially harder.

**Affects.** Every service · the Tool Gateway's validation approach · test strategy · CI configuration ·
dependency and supply-chain management.

**Remains open.** PDF rendering library — HTML-to-PDF gives the best typographic control but adds a
rendering engine, and WeasyPrint has known dependency friction on Windows; needs a spike · whether
tabular work uses pandas or polars.

**Reversibility: Medium.** Provider-neutral boundaries limit the blast radius, but a language change
is a rewrite of everything above the database.

---

## D17 · Orchestration — database state machine with a PostgreSQL queue

**Decision.** Orchestration is a persisted state machine in our own database, driven by stateless
workers consuming a PostgreSQL-backed queue. No workflow engine and no message broker at MVP. Every
state transition and its audit record are written **in the same transaction**. Task handlers are
idempotent, keyed on `{task, attempt, step}`. A scheduler converts time into queue messages. Per-tenant
concurrency limits apply.

**Why.** The product requires execution state to be first-class, tenant-scoped, queryable data in our
own database — invariant I1, and what the console's eight questions read directly. A workflow engine
owns that state in its own datastore, forcing a projection layer and a second copy of the truth in the
one part of the system that must never be inconsistent. Our orchestration is also genuinely simple: six
mostly-sequential tasks, one bounded rework loop, one long human wait.

**Affects.** Orchestrator · worker pool · scheduler · every state transition · audit write path ·
concurrency and fairness.

**Remains open.** Whether the scheduler is a separate process or a leader-elected worker role · the
retry and backoff policy for transient infrastructure failures, which is distinct from D11 rework ·
**how workers see queue rows under RLS — see the new tension below.**

**Reversibility: Medium.** Because states and transitions are explicit and persisted, moving to a
durable engine later is a rewrite of the driver, not of the domain.

---

## D18 · Tenant isolation mechanism — shared schema with PostgreSQL RLS

**Decision.** One schema; `tenant_id` on every tenant-owned record; row-level security enforced by the
database. `ENABLE ROW LEVEL SECURITY` **and** `FORCE ROW LEVEL SECURITY` on every tenant-owned table.
The application role is not a superuser, is not the table owner, and does not hold `BYPASSRLS`. Tenant
context is established **per transaction**, never per session, including in workers and scheduled jobs.
Absent or ambiguous tenant context denies rather than defaults.

**Why.** It is the only option that satisfies D15 literally at a cost a small team can carry.
Schema-per-tenant feels safer than it is and multiplies migration failure modes; database-per-tenant is
right for a specific regulated customer later but would spend most of the team's operational budget on
the wrong problem at 5–20 pilot tenants.

**Affects.** Every table and query · connection and session management · workers and scheduled jobs ·
object storage key layout · caches and derived stores · the adversarial isolation suite.

**Remains open.** How the anchoring job and the queue dispatcher read across tenants without a general
bypass — see the new tensions below · treatment of caches and any future search index · the break-glass
procedure's concrete mechanism.

**Reversibility: Low.** Migration to database-per-tenant for a specific customer remains possible
because the schema is identical, but the isolation approach itself touches every query.

---

## D19 · Database engine — PostgreSQL 16+

**Decision.** PostgreSQL 16 or later.

**Why.** D15 requires database-enforced isolation, which effectively selects PostgreSQL or SQL Server.
PostgreSQL wins on cost, on cloud portability under D3, and above all on consolidation: it serves as
database, queue, and evidence store at MVP scale. Removing an entire infrastructure component is worth
more to a small team than any feature comparison. JSONB suits evidence payloads and pinned definition
snapshots without premature schema commitments; declarative partitioning handles evidence and audit
growth.

**Affects.** Everything. Data access, queue, isolation mechanism, evidence storage, audit chain,
operational tooling.

**Remains open.** Managed offering and version pinning, which follow the still-open cloud provider
decision · partitioning strategy for evidence and audit tables · connection pooling approach, which
interacts with D18's per-transaction context requirement.

**Reversibility: Low.** RLS, JSONB, and `SKIP LOCKED` are all engine-specific and load-bearing.

---

## D20 · Audit chain scope — per-tenant chains anchored into a global chain

**Decision.** Each tenant has an independent hash chain with a per-tenant sequence number and head
record. A separate low-volume **anchor chain** records each tenant chain's head hash on a fixed cadence;
anchor records are themselves chained across all tenants, so they are mutually entangled. A reserved
**platform chain** covers events with no tenant. Cross-boundary events such as break-glass access are
written to both the platform chain and the affected tenant's chain. The anchor chain is **not
tenant-readable**.

The hash input is fixed as:

```
record_hash = H( prev_hash ‖ tenant_id ‖ seq ‖ event_type ‖ actor_id ‖ event_time ‖ H(payload_ciphertext) )
```

**Why.** Hash chaining alone detects modification in the middle of a chain but **not truncation or
wholesale rewrite** — an operator with write access can recompute every hash from any point forward and
produce an internally consistent result. Anchoring is what makes D14's tamper-evidence claim true rather
than aspirational. A single global chain was rejected because a tenant cannot verify it without either a
standing cross-tenant read path that D15 and D18 forbid, or a metadata skeleton that leaks every other
tenant's activity volume and timing.

**Affects.** Audit table design · the chain append path and its per-tenant serialization · the anchoring
scheduler job · verification and export tooling · tenant offboarding · the path to external
notarization.

**Remains open.** Anchor cadence, trading detection window against write volume · whether anchor records
store `tenant_id` or a salted pseudonym · when external notarization of anchor heads is adopted · who
runs verification and how often · **which database role performs anchoring, and under what policy**.
~~The platform chain's encryption key~~ **resolved by D27.**

**Reversibility: Low.** Chain scope cannot be changed retroactively. Adding anchoring later is additive
and does not alter the record format; changing the tenant-scope decision is not.

---

## D21 · Trusted time — database transaction timestamps, order carried by the chain

**Decision.** Platform event time is PostgreSQL `transaction_timestamp()`. Application hosts never
supply a platform timestamp. **The chain sequence number is the authoritative order of events; the
timestamp is evidence of when, not of order.** A monotonicity assertion at append records any backwards
time movement as an integrity anomaly rather than silently accepting or rejecting it. The database
host's clock is disciplined with slewing, its offset monitored, and the observed offset periodically
recorded as a platform audit event. All timestamps are `timestamptz`, UTC at rest. Times reported by
tools or external systems are stored as evidence content, clearly labelled as reported, and never
promoted to platform event time. D7's approval SLA is computed with the same clock. External
notarization of anchor heads is designed for and deferred.

**Why.** Multi-host application clocks skew, and a record whose timestamps contradict causality is
challengeable in full — the credibility cost is not proportional to the size of the skew. Separating
order from time removes the need for perfectly monotonic timestamps. `transaction_timestamp()` is chosen
over `clock_timestamp()` because under D17 a transition and its audit record share one transaction and
should therefore carry one honest timestamp rather than two values implying a precision the system does
not have.

**Affects.** Every audit and evidence write · SLA computation under D7 · export and console ordering ·
database host operational requirements · evidence payload handling.

**Remains open.** Notarization provider and cadence · behaviour on failover to a host with a divergent
clock, beyond recording the anomaly · whether integrity anomalies page immediately or are batched.

**Reversibility: Low** for records already written; **High** for adding attestation later.

---

## D22 · `spreadsheet.write` in the MVP tool set — new workbooks only

**Decision.** Add a `spreadsheet.write` tool to the MVP, scoped to **composing a new workbook artifact
from validated structured data**. In-place modification of an uploaded workbook is **excluded from
MVP**; an uploaded workbook remains immutable. A deterministic workbook integrity check validates that
the produced workbook opens, contains the expected sheets and row counts, and reconciles to its source
dataset.

**Why.** "Give me the analysis in Excel" is the most natural finance expectation, and a PDF plus a
separate chart file is a visibly weaker deliverable. Restricting to generation avoids the round-trip
fidelity trap, where open-source spreadsheet libraries are widely reported to lose charts, pivot tables,
and formatting when re-saving a complex workbook — silently corrupting a controller's workbook would
cost more trust than omitting the feature. Generation from known-good structured data is bounded,
deterministic, and testable, and it keeps provenance sharp: a generated artifact clearly derives from
the validated dataset, whereas an edited upload blurs what the user supplied with what the platform
produced.

This is not a breach of the read-only rule. `PRODUCT.md` §12 prohibits writing to *external business
systems*; producing a versioned artifact inside the platform is artifact production.

**Affects.** MVP tool set · the Finance vertical's task plan · Artifact Definitions for workbook
artifacts · a new deterministic integrity gate · `PRODUCT.md` §11 and §8.3, both now stale — see
Documents requiring amendment.

**Remains open.** The generating library, pending the D16 spike · whether the integrity check is its own
gate or part of the workbook Artifact Definition's validation · in-place workbook editing as a post-MVP
capability with its own fidelity suite.

**Reversibility: High.** Adding or removing a tool is bounded work.

---

## D23 · Canonical serialization — RFC 8785 JCS

**Decision.** JSON Canonicalization Scheme (RFC 8785) is the canonical byte representation for anything
that is hashed. The chain record header is assembled as a JSON object containing every hash input from
D20, canonicalized with JCS, and hashed. Binary values — previous hash, payload ciphertext digest — are
encoded as lowercase hexadecimal strings inside that object.

**Why.** A hash is meaningless without a deterministic byte representation. Key ordering, number
formatting, and Unicode normalization must be fixed before the first record is written, or verification
fails silently later against records that cannot be recomputed. JCS is a published standard with
implementations across languages, which matters for independent verification by an external auditor who
is not running our code.

**Affects.** Chain append and verification · export format · any future notarization · evidence
digesting.

**Remains open.** ~~Whether artifact content digests use the same canonicalization~~ **resolved by
D29** — JCS applies only to structures the platform itself constructs for hashing; all content is
digested as raw bytes.

**Reversibility: Low.** Records hashed under one canonicalization cannot be verified under another.

---

## D24 · Hash algorithm — SHA-256, with a recorded algorithm identifier

**Decision.** SHA-256. **Every chain record stores an explicit `hash_algorithm` identifier.**

**Why.** SHA-256 has ample collision resistance for this purpose and universal implementation support.
The identifier is the more important half of the decision: without it recorded from the first record,
migrating to a different algorithm later is impossible, because verification could not know which
algorithm produced which record. Recording it costs a few bytes and preserves an option that is
otherwise permanently closed.

**Affects.** Chain record structure · verification · export.

**Remains open.** The migration procedure itself, if an algorithm change is ever needed — a mixed-algorithm
chain needs a defined verification rule.

**Reversibility: Medium**, and only because of the identifier. Without it, **Low**.

---

## D25 · Encryption key identifier stored with ciphertext

**Decision.** Every encrypted audit payload and evidence blob records the identifier of the key used to
encrypt it.

**Why.** D1's crypto-shredding requires knowing which key decrypts which ciphertext, and key rotation
requires distinguishing key generations. Without the identifier recorded at write time, rotation becomes
impossible and erasure becomes guesswork.

**Affects.** Audit payload storage · evidence blob storage · artifact content storage · key management ·
the erasure procedure.

**Remains open.** Key hierarchy granularity, carried forward from D1 — per-tenant keys erase a whole
tenant, while GDPR erasure is normally per data subject · rotation cadence · whether the identifier is
itself sensitive.

**Reversibility: Low.** Ciphertext written without a key identifier cannot be reliably attributed later.

---

## D26 · Identifier format — cryptographically random for externally visible entities

**Decision.** Externally visible entity identifiers are cryptographically random and non-enumerable.
Sequential integers are not used for anything reachable from outside the system.

**Why.** `PRODUCT.md` §14 requires cross-tenant identifiers to be neither guessable nor enumerable.
Sequential identifiers leak volume and enable enumeration attacks against the tenant boundary.

**Scope clarification.** This governs *entity identity*. It does **not** govern two things that must
stay ordered: the per-tenant audit chain **sequence number** under D20, which is inherently ordinal and
required for verification; and definition **version numbers** under D9, which are human-facing and
should stay legible as v1, v2, v3. Both remain confined to their own tenant or to platform-curated
content, so neither leaks across the boundary.

**Affects.** Every externally visible entity · URL structure · console linking · export format.

**Remains open.** Which specific scheme — UUIDv4, UUIDv7, or ULID. UUIDv7 and ULID preserve time
ordering for index locality at the cost of disclosing creation time; UUIDv4 discloses nothing and
scatters index writes.

**Reversibility: Low.** Identifiers appear in audit records, exports, and customer-held links.

---

## D27 · Platform chain key — dedicated, never destroyed, and it never holds tenant content

**Decision.** The reserved platform chain encrypts its payloads with a **dedicated platform key**, held
in the same key store as tenant keys and rotated the same way, but **never destroyed** — platform audit
is retained under platform retention, not tenant retention.

Three constraints make that safe:

1. **The platform chain never carries tenant business content.** Payloads hold platform-actor identity,
   tenant *identifiers*, event type, scope, and reason — never tenant data.
2. **Cross-boundary events reference rather than duplicate.** When an event concerns a tenant — a
   break-glass access, an administrative change to a tenant user — the **full record goes to the tenant
   chain** encrypted with the tenant key, and the platform copy carries a **pointer to that record**
   plus platform-side metadata. It is a reference, not a second copy.
3. **The anchor chain is not encrypted at the application layer.** Anchor records contain only
   identifiers, sequence numbers, hashes, and timestamps — no payload. Leaving them in the clear keeps
   verification simple, including future external verification by a party that holds no key. They are
   protected by access control (not tenant-readable) and by database encryption at rest.

**Why.** Encrypting platform events with the *tenant's* key was the tempting option and is wrong: it
would let a tenant erase the platform's own record of its administrative actions, which the platform
needs for its own change-management obligations under `PRODUCT.md` §17. Leaving platform payloads
unencrypted was also rejected — break-glass records and admin identities are Confidential under
`PRODUCT.md` §16, and a chain where some records are encrypted and some are not complicates both
verification and D25's key-identifier rule.

The reference-not-copy rule is what keeps D1 honest. Without it, a platform record saying "admin A
changed user u@tenant.example's role" would survive destruction of that tenant's key, leaving tenant
personal data readable after erasure — silently defeating crypto-shredding.

**Affects.** Key management · platform chain payload structure · the dual-write path for cross-boundary
events · anchor chain storage · platform retention policy, which is now explicitly distinct from tenant
retention.

**Remains open.** Platform audit retention period, which is a separate business decision from D2's
tenant retention · whether platform-actor personal data carries its own erasure obligation for
departing employees.

**Reversibility: Low.** The reference-not-copy rule cannot be applied retroactively to records already
written as copies.

---

## D28 · Identifier scheme — UUIDv7 by default, UUIDv4 for tenant identifiers

**Decision.** UUIDv7 (RFC 9562) is the default identifier for all entities, stored as PostgreSQL `uuid`.
**Tenant identifiers are UUIDv4.**

**Why.** D26 fixed the property — cryptographically random and non-enumerable — and left the scheme
open. UUIDv7's 74 non-timestamp bits satisfy non-enumerability with enormous margin, while its
time-ordered prefix gives index locality on exactly the tables that grow fastest: actions, evidence, and
audit records, where `PRODUCT.md` §15 allows 10,000 evidence records per execution held for seven years
under D2. Fully random identifiers on those tables cause index fragmentation and long-term bloat for no
security benefit anyone can name.

The exception exists because UUIDv7 discloses creation time, and one identifier should disclose nothing
at all: **the tenant identifier is the isolation boundary.** Tenants are also low-volume, so index
locality is worth nothing there. Paying UUIDv4's cost where it buys something and not where it doesn't
is the whole of this decision.

Creation-time disclosure was weighed for other entities and judged immaterial: whoever holds an
execution or artifact identifier already knows roughly when it was made, and the timestamp is in the
audit record for anyone authorized to read it.

**Affects.** Every entity identifier · URL structure · index design · export format · console linking.

**Remains open.** PostgreSQL 16 has no native UUIDv7 function — `gen_random_uuid()` produces v4 — so v7
values are generated in the application layer under D16. Whether to adopt native generation on a later
PostgreSQL is a routine upgrade question · whether to add a separate internal surrogate key alongside
the external identifier if write volume ever demands it, which is additive and low cost.

**Reversibility: Low.** Identifiers appear in audit records, exports, and customer-held links.

---

## D29 · Content digests — raw bytes; JCS only for platform-constructed structures

**Decision.** All **content** is digested over its exact raw bytes: artifact content of every type,
evidence blobs, and encrypted payloads. RFC 8785 canonicalization under D23 applies **only** to JSON
structures the platform itself constructs for hashing — specifically the chain record header. The hash
algorithm is SHA-256 with a recorded identifier per D24.

**Why.** Content integrity and semantic equivalence are different questions, and conflating them breaks
the first one. Canonicalizing before hashing would make two byte-different files produce the same
digest — which means the platform could serve a file that is not byte-identical to the one a Control
Gate approved. For a product whose claim is that the approved artifact and the delivered artifact are
the same object, that is an integrity failure, not an optimisation. It also cannot work at all for
XLSX, PDF, or PNG, which have no canonical JSON form.

Raw-byte digesting is what makes I6 provable: an artifact version is immutable because its digest fixes
its bytes.

**Affects.** Artifact Service · Evidence Recorder · chain record construction, where `H(payload_ciphertext)`
is a raw-byte digest · gate evaluation · export and verification tooling.

**Remains open.** If a gate ever needs semantic equivalence between two structured artifacts — "is this
dataset the same as the previous version, ignoring key order?" — that requires a **second, canonical
digest recorded alongside** the content digest, never replacing it. Not needed for MVP; the rule is
recorded so nobody reaches for canonicalization when the need appears.

**Reversibility: Low.** Digests already written under one rule cannot be reinterpreted under another.

---

## D30 · Platform-curated definitions are not tenant-scoped

**Decision.** Definition tables — agent definitions, skills, and later artifact and
gate definitions, together with their version rows — carry no `tenant_id` and are
readable by every tenant. Invariant I13 is amended from "exactly two" to name them
as a third structure outside tenant scope.

**Why.** D5 makes MVP departments platform-curated, so a definition is platform
content rather than tenant content. There is no tenant boundary to cross, because
no tenant owns the row. Replicating identical definitions per tenant would create
a boundary that exists only to be crossed, and would make D9's version pinning
ambiguous across copies.

**Affects.** Schema for every definition table · the RLS policy-coverage test,
which must exempt them explicitly rather than by accident · Task 4 onward.

**Remains open.** When D5's tenant-authored departments arrive post-MVP, definitions
become partly tenant-owned and this decision needs revisiting — a tenant-authored
definition is tenant content and must be scoped.

**Reversibility: Medium.** Adding `tenant_id` later means backfilling and
re-pinning every historical reference.

---

## Cross-decision tensions

These arise from the decisions interacting, not from any single one. Architecture must resolve them
explicitly.

1. **D1 × D2 — erasure versus legal retention.** A statutory retention obligation can override an
   erasure request. The platform needs an explicit precedence rule and must record which applied.
2. **D1 × D14 — shredding preserves what deletion severs.** Key destruction keeps the hash chain
   intact; row deletion breaks it. Retention expiry should therefore be implemented as shredding plus
   hash-retaining tombstones, never as deletion. The two decisions reinforce each other.
3. **D14 × D15 — chain scope versus isolation. RESOLVED by D20.** A global audit chain structurally
   spans tenants and cannot be verified by a tenant without either a cross-tenant read path or a
   metadata leak. Per-tenant chains anchored into an entangled global anchor chain reconcile the two:
   records stay tenant-scoped, and entanglement lives in the anchor layer where it carries only hashes.
   Retained here because the reasoning still governs the design.
4. **D4 × D7 — no self-review versus small tenants.** A tenant with one qualified approver deadlocks,
   and no SLA can fix an approver who does not exist. This is a go-to-market constraint, not just an
   engineering one.
5. **D12 × Finance G4.** Redaction must not remove or alter the figures that the narrative
   traceability gate depends on. Over-redaction corrupts artifacts silently.
6. **D3 × D1/D2 — single region versus residency.** GDPR-sensitive or in-region customers may force a
   second region earlier than the MVP plan assumes.
7. **D6 × D11 — two paths into one queue.** A task exhausting its rework budget and an execution
   awaiting final approval both arrive in Needs Attention. The queue must distinguish them, because
   one is a failure and the other is normal.
8. **D10 × D13 — the defense that actually holds.** Keeping permission strictly outside instruction is
   what prevents injected content from escalating privilege. These two decisions are one mechanism
   described from two directions.

Three further tensions surfaced when D16–D26 were checked against D1–D15. None invalidates a decision;
each names a mechanism that must be settled before implementation.

9. **D17 × D18 — how a worker sees a queue row before it has tenant context.** RLS requires tenant
   context to be set per transaction, but a worker cannot know which tenant's job to claim until it has
   read the queue. The resolution is that **the dispatch queue is platform-scoped, not tenant-scoped**:
   it carries `tenant_id` as a routing field and no tenant payload whatsoever. A worker claims a row,
   establishes tenant context from it, and only then touches tenant data. Per-tenant concurrency limits
   read the same platform-scoped dispatch metadata. This is a deliberate, narrow exception to blanket
   tenant RLS and must be documented as such, with an enforced rule that the queue never carries
   business content.

10. **D20 × D18 — how the anchoring job reads every tenant's chain head.** Anchoring requires reading
    all tenants' chain heads, but D18 withholds `BYPASSRLS` from the application role. The resolution is
    a **separate, narrowly-privileged database role** whose policy permits cross-tenant `SELECT` of
    chain-head hashes only — never audit payloads, never business data. This is the single place in the
    system where a permanent cross-tenant read exists by design; it is not break-glass, so it needs
    explicit documentation and its own test coverage rather than being treated as an operational detail.

11. **D20 × D1 — the platform chain has no tenant key, and cross-boundary events are written twice.**
    Two consequences. First, the reserved platform chain needs its own encryption key, since it has no
    tenant to draw one from. Second, a break-glass event recorded in both the platform chain and the
    tenant chain must keep the **platform copy free of tenant content** — metadata only: who, when, what
    scope. Otherwise shredding a tenant's key would leave that tenant's data readable in the platform
    chain, silently defeating D1.

---

## Effect on `PRODUCT.md` §26

**Closed by this record:** #1 erasure (D1) · #2 retention, mechanism and default (D2) · #4
self-review (D4) · #5 department authorship (D5) · #6 human-optional gates (D6) · #7 approval SLA
default and expiry behavior (D7).

**Partially closed:** #3 deployment — topology and region count fixed (D3), cloud provider still
open · #8 LLM provider — requirements fixed (D8), selection still open.

**Still open, unaffected:** #9 model tiering · #10 sandbox technology · #11 first ERP integration ·
#12 ICP validation · #13 time-savings baseline · #14 RPO/RTO targets · #15 RTL and localization ·
#16 materiality threshold defaults · #17 pricing model. Plus the escalation target from #7.

**Closed by the 2026-08-12 acceptance:** #3 cloud deployment is now fully specified for topology,
engine, and isolation by D18 and D19, though the cloud *provider* remains open.

## Documents requiring amendment

Recorded, not performed. `CLAUDE.md`, `DESIGN.md`, and `PRODUCT.md` were **not** modified in this
change and are now known to be stale in the ways listed below.

| Document | Amendment | Raised by |
|---|---|---|
| `CLAUDE.md` §2 | Add **Department** and **Agent Runtime** to the glossary | `PRODUCT.md` §7 |
| `CLAUDE.md` §4 | Add prompt injection as a named threat (D13); state redaction-before-persistence (D12) | D12, D13 |
| `CLAUDE.md` §9, §11 | Remove the stale "once it exists" clause for `DESIGN.md`; update the git remote note | Readiness review |
| `DESIGN.md` §9.4, §15.2 | Correct render-time redaction to redaction-at-ingest (D12) | D12 |
| **`PRODUCT.md` §11** | **Add `spreadsheet.write` to the MVP tool set, scoped to new-workbook generation.** §11 currently fixes a six-tool set that excludes it, which now contradicts D22 | **D22** |
| **`PRODUCT.md` §8.3** | **Add the deterministic workbook integrity check to the Finance gate table**, which currently lists G1–G5 only | **D22** |
| `PRODUCT.md` §26 | Mark the closed and partially closed decisions, with references here | D16–D26 |
