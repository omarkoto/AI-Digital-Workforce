# Phase 1 Implementation Plan — Execution Record Core

**Goal.** Build the persisted spine of the platform: executions, tasks, actions, evidence, artifacts,
gates, rework, approvals, and a tamper-evident per-tenant audit chain — proven by driving one scripted
execution end to end, reconstructing it from the database alone, and detecting deliberate tampering.

**Architecture.** A FastAPI service and a stateless worker pool over one PostgreSQL 16 database, which
also carries the dispatch queue. All execution state is persisted; workers are resumable. Tenant
isolation is enforced by row-level security, not application filters. Every state transition writes its
audit chain record in the same transaction.

**Tech stack.** Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.x · Alembic · PostgreSQL 16 ·
pytest. No broker, no cache, no other datastore.

**Status.** Plan only. No code is written until this is approved.

---

## Global constraints

Copied from the accepted decisions. Every task inherits these.

| | Constraint | Source |
|---|---|---|
| G1 | Python 3.12; `mypy --strict` fails the build; Pydantic at every trust boundary; process-based workers; dependency lockfile + vulnerability scanning | D16 |
| G2 | Every state transition and its audit record are written **in one transaction**; handlers idempotent on `{task, attempt, step}` | D17 |
| G3 | `ENABLE` + `FORCE ROW LEVEL SECURITY` on every tenant-owned table; app role is not superuser, not table owner, no `BYPASSRLS`; tenant context set **per transaction**; missing or ambiguous context denies | D18 |
| G4 | PostgreSQL 16+ only. No Redis, RabbitMQ, Kafka, Temporal, MongoDB, or any second datastore | D19, G4 of the brief |
| G5 | Per-tenant hash chains; entangled anchor chain; reserved platform chain; anchor chain not tenant-readable | D20 |
| G6 | Event time is `transaction_timestamp()`; **the chain sequence is the authoritative order**; backwards time is recorded as an integrity anomaly | D21 |
| G7 | RFC 8785 JCS for platform-built hash structures; binary values as lowercase hex | D23 |
| G8 | SHA-256, with `hash_algorithm` stored on every chain record | D24 |
| G9 | Encryption key identifier stored with every ciphertext | D25 |
| G10 | UUIDv7 by default; **UUIDv4 for tenant identifiers**; generated in the application (PG16 has no native v7) | D26, D28 |
| G11 | Content digests over **raw bytes**; JCS only for platform-constructed structures | D29 |
| G12 | Redaction happens **before** persistence, never at render | D12, I3 |
| G13 | Artifact versions are immutable; update means new version | I6 |
| G14 | Producer identity can never equal approver identity | D4, I5 |
| G15 | An action cannot reach `succeeded` without linked evidence | I10 |
| G16 | Only two structures may be read cross-tenant — the dispatch queue and the anchoring chain-head read — both identifiers and hashes only, never business content | I13 |

---

## 0. Repository state found

| Item | Finding |
|---|---|
| Implementation code | **None.** No `.py`, `.sql`, `.toml`, `.cfg`, `.yaml`, `Dockerfile`, or `Makefile` |
| Dependency manifest | **None** |
| Directories | `docs/` only |
| Files | 7 Markdown documents |
| Git | 2 commits (`c9c9ac1`, `75788b4 Setup`), clean tree |
| Remote | **`origin` → `github.com/omarkoto/AI-Digital-Workforce.git`** — the previously reported gap is closed |
| CI | **None** |

This is a greenfield build. Nothing is inherited and nothing needs migrating.

---

## 1. Project and backend structure

**What it does.** Fixes module boundaries before any code exists, so responsibilities do not drift.

**Why we need it.** `CLAUDE.md` §6 requires small, testable modules and business logic independent of
any provider. The layering below makes the domain layer runnable with no database and no network,
which is what makes the state machines and hashing testable in isolation.

```
pyproject.toml                 # deps, mypy --strict, pytest, ruff config
alembic.ini
src/adw/
  config.py                    # settings via Pydantic Settings; fails fast on missing values
  db.py                        # engine, session factory, per-transaction tenant context wiring
  domain/                      # PURE: no I/O, no SQLAlchemy, no network
    ids.py                     # UUIDv7 / UUIDv4 generation (G10)
    states.py                  # every state enum
    transitions.py             # legal transition tables for each machine
    canonical.py               # RFC 8785 JCS serialization (G7)
    hashing.py                 # SHA-256 over raw bytes and over canonical structures (G8, G11)
    chain.py                   # chain record hash computation, pure function
    errors.py
  ports/                       # interfaces only, no implementations
    keystore.py                # resolve/rotate keys by key_id
    blobstore.py               # put/get bytes by content digest
    clock.py                   # exposes the DB clock, not the host clock
  adapters/
    keystore_local.py          # dev-only, file-backed
    blobstore_local.py         # dev-only, filesystem-backed
  models/                      # SQLAlchemy 2.x declarative models
    base.py  tenant.py  definition.py  execution.py  task.py  action.py
    evidence.py  artifact.py  gate.py  rework.py  approval.py
    audit.py  anchor.py  queue.py
  services/                    # one responsibility each, all transactional
    tenant_context.py  execution_service.py  task_service.py
    action_recorder.py  evidence_recorder.py  artifact_service.py
    gate_engine.py  rework_controller.py  approval_service.py
    audit_writer.py  anchor_writer.py  redaction.py
  workers/
    dispatcher.py              # SKIP LOCKED claim loop
    handlers.py                # job_type -> handler registry
    scheduler.py               # SLA expiry, anchoring cadence
  verification/
    chain_verifier.py          # verify a tenant chain and the anchor chain
    reconstructor.py           # rebuild an execution narrative from the DB alone
  api/
    app.py  deps.py
    routes/                    # executions, tasks, artifacts, gates, approvals, admin
    schemas/                   # Pydantic v2 request/response models
  stubs/                       # PHASE 1 ONLY — scripted agent + canned tools
    scripted_agent.py  canned_tools.py
migrations/versions/
tests/
  unit/  integration/  security/  scenario/
```

**Must NOT.** `domain/` must not import SQLAlchemy, FastAPI, or any adapter. `models/` must not contain
business logic. `services/` must not import from `api/`. `stubs/` must not be importable from any
production path — enforced by a test.

---

## 2. Python 3.12 + FastAPI setup

**What it does.** Establishes the runtime, dependency lock, type checking, linting, and the API skeleton.

**Why we need it.** G1 makes `mypy --strict` and Pydantic-at-boundaries build-failing gates, so they
must exist before the first domain module, not after.

**Communicates with.** Nothing at runtime — it is the container everything else runs in.

**Must NOT.** No business logic in `app.py`. No dependency added without a lockfile entry. No
`# type: ignore` without a written justification.

**Concretely:** `pyproject.toml` with pinned direct dependencies and a lockfile · `mypy` in strict mode
over `src/` · `ruff` for lint and format · `pytest` with markers `unit`, `integration`, `security`,
`scenario` · a health route and nothing else.

## 3. PostgreSQL 16+

**What it does.** The single datastore: state, audit, evidence metadata, and the dispatch queue.

**Why we need it.** D19 chose it for four jobs at once — RLS for isolation, JSONB for payloads,
`SKIP LOCKED` for the queue, partitioning for growth.

**Communicates with.** API service, worker pool, scheduler. Never the browser, never a stub agent.

**Must NOT.** No second datastore may be introduced (G4). The application role must never be granted
superuser, table ownership, or `BYPASSRLS`.

**Roles to create in migration 0001:**

| Role | Purpose | Privileges |
|---|---|---|
| `adw_owner` | Owns tables, runs migrations | DDL; used only by Alembic |
| `adw_app` | API and workers | DML on tenant tables; **no `BYPASSRLS`**, not owner |
| `adw_anchor` | Anchoring job | `SELECT` on `chain_head` **only**, cross-tenant; `INSERT` on `anchor_record` |
| `adw_auditor` | Read-only audit access | `SELECT` on chain and anchor tables |

**Clock requirement:** the database host's clock is disciplined with slewing and its offset monitored
(D21). Phase 1 records the observed offset as a periodic platform chain event.

## 4. SQLAlchemy 2.x

**What it does.** Typed data access and unit-of-work transaction boundaries.

**Why we need it.** Transactions are the correctness mechanism for G2 — a transition and its audit
record share one.

**Communicates with.** `models/` and `services/`.

**Must NOT.** No lazy loading in worker paths. No implicit autocommit. No raw SQL outside migrations
and the two explicitly documented cross-tenant reads (G16). **No session-level tenant context** — it
must be `SET LOCAL` inside the transaction, because connection pooling reuses sessions across tenants.

## 5. Alembic migrations

**What it does.** Versioned schema evolution, including roles, RLS policies, and grants.

**Why we need it.** RLS policies and grants are schema, not configuration. If they are not in
migrations, they are not reproducible, and the isolation guarantee becomes an environment accident.

**Communicates with.** PostgreSQL, as `adw_owner`.

**Must NOT.** Must not run as `adw_app`. Must never drop or alter an audit, evidence, or artifact
version row. Every migration that creates a tenant-owned table must, in the same migration, enable and
force RLS and create its policy — enforced by a test that scans for tenant tables lacking a policy.

## 6. Pydantic v2

**What it does.** Runtime validation at every trust boundary — API input and output, tool input and
output, and the stub agent's proposals.

**Why we need it.** G1 treats boundary validation as a security control, not ergonomics.

**Communicates with.** `api/schemas/`, the stub tool interface.

**Must NOT.** Pydantic models must not be reused as SQLAlchemy models. Validation must never be
skipped on an internal path "because it came from us."

## 7. Tenant model and RLS strategy

**What it does.** Represents a tenant and enforces that no query crosses a tenant boundary.

**Why we need it.** D15 and D18. This is the least reversible thing in the system.

**Communicates with.** Every model and every service.

**Must NOT.** Must never rely on an application `WHERE` clause as the isolation mechanism. Must never
default a missing tenant context to any value.

**Mechanism:**
- Every tenant-owned table carries `tenant_id UUID NOT NULL`.
- Policy shape: `USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)`. When the
  setting is absent the comparison yields NULL, which is not true, so **zero rows** — fail closed.
- `db.py` provides one transaction helper that issues `SET LOCAL app.tenant_id` as the first statement
  and refuses to open a tenant transaction without an explicit tenant.
- Worker and scheduler paths use the same helper. There is exactly one way to open a tenant
  transaction, so there is exactly one place to get it wrong.
- **Platform-scoped tables** — `dispatch_queue`, `anchor_record`, `anchor_head` — carry no tenant policy
  and are governed by role grants (G16).

**Reserved platform tenant.** The platform chain lives in the same chain tables under the reserved
identifier `00000000-0000-0000-0000-000000000000`. It is deliberately not a valid UUIDv4, so it can
never collide with a real tenant.

## 8. Execution model

**What it does.** One run of one requirement for one tenant. The root of everything and the unit of
budget, audit, and delivery.

**Why we need it.** `ARCHITECTURE.md` §5.6.

**Communicates with.** Task, Artifact, Approval, the audit chain, the dispatch queue.

**Must NOT.** Must not hold agent reasoning, tool results, or artifact content. Must not be deleted —
only shredded via key destruction at retention expiry.

**Holds:** id (v7) · tenant_id · requester identity · requirement text (**ciphertext + key_id**) ·
state · plan reference · created/updated times · budget counters.

**States:** `Draft → Planning → AwaitingConfirmation → Running → AwaitingApproval → Completed`, with
`Failed`, `Blocked`, `Cancelled`, and `Expired` as alternates.

## 9. Task model

**What it does.** The unit of assignment and the unit of permission.

**Why we need it.** Tasks are what make grants small, rework local, and progress legible.

**Communicates with.** Execution (parent), Action, ArtifactVersion, GateDecision, ReworkAttempt,
dispatch queue.

**Must NOT.** Must not decide its own completion. Must not decide gates on its own output. Must not
carry permission — grants are separate records (deferred to Phase 3, but the foreign key exists now).

**Holds:** id (v7) · tenant_id · execution_id · sequence in plan · pinned agent definition version ·
pinned skill versions · state · attempt counter · inputs and expected outputs as references.

## 10. Task state machine

**What it does.** Declares the legal transitions and rejects everything else.

**Why we need it.** `CLAUDE.md` §6 requires explicit state machines rather than status strings mutated
across the codebase.

**Communicates with.** `task_service`, which is the only writer of task state.

**Must NOT.** No component other than `task_service` may write task state. No transition may occur
without an audit chain record in the same transaction (G2).

**Transitions** (from `ARCHITECTURE.md` §5.8):

```
Planned    → Queued
Queued     → Running
Running    → Producing | Failed
Producing  → AwaitingGate
AwaitingGate → Passed | Reworking
Reworking  → Queued   (attempts < 3)
Reworking  → Blocked  (attempts = 3)
Failed     → Blocked
Blocked    → Queued   (explicit human decision)
Passed     → terminal
```

Implemented as a frozen mapping in `domain/transitions.py`, with a test that asserts **every** pair not
in the table is rejected — not a sample.

## 11. Action model

**What it does.** Records one tool invocation and its six-state lifecycle.

**Why we need it.** It is the mechanical implementation of `CLAUDE.md` §3. The distinction between
planned, attempted, executed, succeeded, and failed only exists if something records it as distinct
states.

**Communicates with.** Task (parent), Evidence, the audit chain.

**Must NOT. Must not reach `succeeded` without at least one linked evidence row (G15).** Must not be
updated after reaching a terminal state. Must not store tool payloads inline — those are evidence.

**States:** `planned → attempted → executed → succeeded | failed`, plus `unverified` for a reported
completion with no evidence.

## 12. Evidence model

**What it does.** Stores the recorded proof of what happened, redacted before it is written.

**Why we need it.** Without it every claim in the product is an assertion.

**Communicates with.** Action **or** GateDecision — exactly one, enforced by an XOR check constraint ·
BlobStore · KeyStore.

**Must NOT.** Must not be written before redaction runs (G12). Must not be mutated or deleted. Must not
be re-redacted at read time. Must not accept a write from anything other than the recorder service.

**Holds:** id (v7) · tenant_id · action_id XOR gate_decision_id · kind · inline ciphertext **or** blob
reference · `key_id` (G9) · `content_digest` over raw bytes (G11) · byte size · created_at.

**Inline vs blob threshold: 64 KiB proposed** — open decision **I**, see §32.

## 13. Artifact model

**What it does.** Artifact identity plus an ordered list of immutable versions.

**Why we need it.** Artifacts are the deliverable, and their immutability and lineage are what make the
record defensible.

**Communicates with.** Task (producer), GateDecision, ArtifactDefinition, BlobStore, KeyStore.

**Must NOT.** A version must never be updated or deleted (G13). Content must never be stored in the
relational row. Must not validate its own content — that is the gate engine.

**Enforcement of immutability:** revoke `UPDATE` and `DELETE` on `artifact_version` from `adw_app`, and
add a trigger that raises on either. Both are tested.

## 14. Artifact Definition model

**What it does.** The versioned contract an artifact is validated against.

**Why we need it.** A gate needs something to check against; an artifact type with no definition cannot
pass a gate.

**Communicates with.** ArtifactVersion (pinned reference), GateDefinition.

**Must NOT.** Must not execute validation — it declares rules, the gate engine runs them. A version
referenced by any artifact must never be mutated or hard-deleted, only deprecated (D9).

**Phase 1 scope:** minimal definition records seeded by fixture, sufficient to prove pinning. The
authoring surface is Phase 2 (open decision F).

## 15. Control Gate model

**What it does.** GateDefinition (versioned rule) and GateDecision (the runtime verdict).

**Why we need it.** It is the mandatory checkpoint and, per D13, the primary compensating control
against a model being confidently wrong.

**Communicates with.** ArtifactVersion, Evidence, ApprovalService, ReworkController, audit chain.

**Must NOT.** Must not fix anything. Must not produce artifacts. Must not override a human verdict.
Must not decide a gate where producer and approver resolve to the same identity (G14).

## 16. Gate verdict

**What it does.** Records `PASS | FAIL | WAIVED` with everything needed to defend it.

**Why we need it.** `DESIGN.md` §11.5 requires a verdict never to appear without approver, timestamp,
artifact version, and rule.

**Communicates with.** GateDefinition, ArtifactVersion, Evidence, ReworkController.

**Must NOT.** Must not be recorded with a null decider. Must not present a model-assessed verdict as
deterministic — `evaluation_kind` is required.

**Holds:** id (v7) · tenant_id · gate_definition_version · artifact_version_id · verdict ·
`decided_by_identity` · `producer_identity` · decided_at · rule_id · `evaluation_kind`
(`deterministic | model_assessed`) · failure detail.

**G14 is enforced by a table CHECK constraint** `decided_by_identity <> producer_identity`, because both
columns live on the same row. This satisfies `CLAUDE.md` §3's requirement that self-approval be blocked
in code rather than by instruction.

**Phase 1 evaluators:** the gate engine ships an evaluator interface plus **two trivial built-in
evaluators used only by the scenario test** — a field-presence check and a
"every referenced figure exists in the referenced dataset" check. These prove the mechanism and the
FAIL path. They are **not** the Finance gates, which are out of scope.

## 17. Rework attempt

**What it does.** Turns a FAIL verdict into a bounded, visible retry.

**Why we need it.** Failure must be a first-class counted path, not an invisible loop.

**Communicates with.** GateDecision (trigger), Task, ApprovalService on limit breach.

**Must NOT.** Must not exceed 3 attempts per task (D11). Must not modify artifacts. Must not retry
transient infrastructure errors — those are a different mechanism at the worker layer.

**Holds:** id (v7) · tenant_id · task_id · `attempt_no` with `CHECK (attempt_no BETWEEN 1 AND 3)` ·
triggering gate decision · failure detail · created_at.

## 18. Human approval record

**What it does.** The pending human gate, its SLA, its escalation, and its outcome.

**Why we need it.** D6 makes a human final gate mandatory for every execution.

**Communicates with.** GateDecision, Scheduler (expiry), API (verdict capture), audit chain.

**Must NOT. Expiry must never approve, never reject, and never silently proceed** (D7). Must never
list the requester or the producer as an eligible approver (G14).

**Holds:** id (v7) · tenant_id · gate_decision_id · state (`Pending | Approved | Rejected | Expired`) ·
`sla_deadline` computed as `transaction_timestamp() + interval '72 hours'` · eligible approver set ·
decided_by · decided_at · escalation records.

## 19. Audit record

**What it does.** One entry in a chain, carrying what happened and binding it to what came before.

**Why we need it.** `PRODUCT.md` §24 — the audit record is the product.

**Communicates with.** Every service, write-only. `chain_head` for serialization.

**Must NOT.** Must never be updated or deleted through the application — `UPDATE` and `DELETE` are
revoked from `adw_app` and blocked by trigger. Must never store plaintext payloads. Must never derive
event order from the timestamp (G6).

**Holds:** id (v7) · tenant_id · `seq` (per-tenant, gap-free) · `prev_hash` · `event_type` ·
`actor_id` · `event_time` · `payload_ciphertext` · `payload_digest` · `key_id` (G9) ·
`hash_algorithm` (G8) · `record_hash`.

## 20. Per-tenant hash chain

**What it does.** Links a tenant's audit records so mid-chain modification is detectable.

**Why we need it.** D14 and D20.

**Communicates with.** `audit_writer` (sole writer), `chain_verifier`, `anchor_writer` (reads head).

**Must NOT.** Must not hash plaintext (I12) — the hash covers the ciphertext digest, so verification
survives key destruction under D1. Must not span tenants.

**Hash input**, assembled as a JSON object, canonicalized with JCS (G7), binaries as lowercase hex:

```
record_hash = SHA256( JCS{ prev_hash, tenant_id, seq, event_type, actor_id,
                           event_time, payload_digest, hash_algorithm, key_id } )
```

**Serialization:** appends take `SELECT ... FOR UPDATE` on that tenant's `chain_head` row, so contention
is per-tenant and one tenant's load cannot slow another's transitions.

## 21. Platform anchor

**What it does.** Periodically records each tenant chain's head into a chain that is entangled across
all tenants, making truncation and wholesale rewrite detectable.

**Why we need it.** Plain chaining detects mid-chain edits but not truncation or rewrite. Anchoring is
what makes the tamper-evidence claim true.

**Communicates with.** `chain_head` (read, as `adw_anchor`), `anchor_head`, scheduler.

**Must NOT.** Must not be tenant-readable. Must not contain any payload — identifiers, sequences,
hashes, and times only (G16). Must not be encrypted at the application layer (D27), so that a future
external verifier holding no key can still check it.

**Holds:** `anchor_seq` (global) · `prev_anchor_hash` · tenant_id · `tenant_seq` · `tenant_head_hash` ·
`anchor_time` · `anchor_hash`.

**Cadence: every 100 tenant chain records or 300 seconds, whichever first** — proposed, open decision
**P1**, see §32.

## 22. Trusted timestamps

**What it does.** Supplies one authoritative clock and detects when it misbehaves.

**Why we need it.** D21. Timestamps are evidence; multi-host clocks skew.

**Communicates with.** Every write path, through `ports/clock.py`.

**Must NOT.** Application hosts must never supply a platform timestamp — `datetime.now()` is banned in
`services/` and `models/`, enforced by a lint rule. Must never be used to establish event order (G6).

**Mechanism:** `transaction_timestamp()` as a column default. At append, `audit_writer` compares the new
`event_time` to the head's; if it is earlier, it writes an **integrity anomaly** to the platform chain
and proceeds — neither silently accepting nor silently rejecting.

## 23. UUIDv7 / UUIDv4 rules

**What it does.** Generates identifiers with the right property for each entity.

**Why we need it.** D28. v7 gives index locality on the fast-growing tables; v4 gives zero disclosure
where the isolation boundary is.

**Communicates with.** Every model, at insert.

**Must NOT.** Must never use a sequential integer for an externally visible identifier. Must never use
v7 for a tenant identifier.

**Rules:** tenant → **v4** · everything else → **v7**, generated in Python since PG16 has no native
function · chain `seq` and definition version numbers stay ordinal and are **not** covered by this rule.

## 24. SHA-256 hashing

**What it does.** One hash function, one canonicalization rule, two application modes.

**Why we need it.** G8 and G11.

**Communicates with.** Chain writer, evidence recorder, artifact service, verifier.

**Must NOT.** Must never canonicalize content before digesting it — that would let two byte-different
files share a digest and allow serving a file that is not the one a gate approved (D29).

**Two modes, never mixed:** raw-byte SHA-256 for all *content* — artifacts, evidence blobs, ciphertext
payloads · JCS-then-SHA-256 for *platform-constructed structures*, which in Phase 1 means only the chain
record header and the anchor record header.

## 25. Encryption and key identifier fields

**What it does.** Encrypts payloads with a per-tenant key and records which key was used.

**Why we need it.** D1 crypto-shredding and D25.

**Communicates with.** `ports/keystore.py`.

**Must NOT.** Must never write ciphertext without a `key_id`. Must never encrypt the platform chain with
a tenant key (D27). Must never place tenant business content in the platform chain — cross-boundary
events store a **reference** to the tenant record, not a copy.

**Encryption boundary — proposed rule needing sign-off (§32).** Free-text and payload fields are
encrypted; identifiers, enums, timestamps, counts, and hashes are not, because they must remain
queryable. Unencrypted metadata therefore survives shredding, which D1 already lists as an open question
for legal input.

**Phase 1 KeyStore:** a port with a dev-only local implementation. A real KMS is deferred because the
cloud provider is undecided. The dev adapter must refuse to start when the environment is not `dev`.

## 26. Queue model

**What it does.** Durable dispatch rows claimed with `SELECT ... FOR UPDATE SKIP LOCKED`.

**Why we need it.** D17 chose a database queue so no broker is needed and dispatch shares the state
transaction.

**Communicates with.** API (enqueue), scheduler (enqueue), dispatcher (claim).

**Must NOT. Must carry no business content** — this is a security boundary, not a convention (G16).
Must not be tenant-RLS-protected, because a worker cannot establish tenant context until it has read the
row; access is governed by role grant instead.

**Holds exactly:** id (v7) · tenant_id · job_type · target_id · idempotency_key · available_at ·
claimed_at · claimed_by · attempts · state. Nothing else — enforced by a column allowlist test.

## 27. Worker model

**What it does.** A stateless process that claims a job, establishes tenant context, runs a handler, and
commits.

**Why we need it.** Executions outlive HTTP requests and pause for up to 72 hours.

**Communicates with.** Queue, all services, the scheduler.

**Must NOT.** Must hold no workflow state in memory between jobs. Must not touch tenant data before
establishing tenant context. Must not be the only copy of anything.

**Loop:** claim (platform-scoped read) → open tenant transaction with the claimed `tenant_id` → check
idempotency → run handler → write transition + audit record in one transaction → commit → release.

**Per-tenant concurrency limit** is applied at claim time by counting that tenant's in-flight rows.

**Scheduler:** leader-elected worker role using a PostgreSQL advisory lock rather than a separate
process — proposed, open decision **P5**, see §32.

## 28. Idempotency strategy

**What it does.** Guarantees that a redelivered job produces no second effect.

**Why we need it.** G2, and because at-least-once delivery is the only delivery a database queue
provides.

**Communicates with.** Dispatcher, every handler.

**Must NOT.** Must not rely on handler logic being "naturally" idempotent. Must not silently swallow a
duplicate — it is recorded as an observed duplicate.

**Mechanism:** a `job_execution` table with a unique constraint on `(tenant_id, idempotency_key)` where
the key is `{task_id, attempt_no, step}`. A handler that finds a completed key returns its recorded
outcome without re-running. Insert and effect share the job's transaction, so partial application is
impossible.

---

## Testing

Real PostgreSQL is required — RLS, `SKIP LOCKED`, triggers, and role privileges cannot be tested on
SQLite. See §33 for the prerequisite this creates.

## 29. Required tests

| Area | Test |
|---|---|
| State machines | Every pair **not** in the transition table is rejected — exhaustive, not sampled |
| Action lifecycle | `succeeded` without linked evidence is refused (G15) |
| Artifact immutability | `UPDATE` and `DELETE` on `artifact_version` fail for `adw_app`, by grant and by trigger (G13) |
| Rework | A fourth attempt is refused and the task moves to `Blocked` (D11) |
| Approval SLA | An expired approval becomes `Expired`, never `Approved` (D7) |
| Producer ≠ approver | The CHECK constraint rejects a self-approval (G14) |
| Definition pinning | A task records exact versions and still resolves them after the definition advances (D9) |
| Idempotency | A redelivered job produces exactly one effect |
| Timestamps | Every `event_time` originates from the database, never the host (G6) |
| Anomaly | A backwards timestamp writes a platform-chain anomaly and does not abort |
| Canonicalization | JCS output matches RFC 8785 vectors; digests are stable across key reordering |
| Digest mode | Content is digested raw; two semantically equal but byte-different JSON files produce **different** digests (D29) |

## 30. Security tests

| Area | Test |
|---|---|
| Role privileges | `adw_app` has no `BYPASSRLS`, is not superuser, is not table owner |
| Anchor role | `adw_anchor` can read `chain_head` and nothing else — every other cross-tenant read fails |
| Queue contents | `dispatch_queue` columns match an explicit allowlist; adding a payload column fails the build (G16) |
| Anchor contents | `anchor_record` columns match an explicit allowlist (G16) |
| Redaction order | A tool result containing a secret pattern is redacted **before** insert; the raw value never appears in any row or blob (G12) |
| Key identifier | No ciphertext row exists without a `key_id` (G9) |
| Platform chain purity | No platform chain record contains tenant business content — cross-boundary events store a reference (D27) |
| Stub isolation | No production module imports from `stubs/` |
| Dev adapters | Local KeyStore and BlobStore refuse to start outside `dev` |
| Policy coverage | Every tenant-owned table has RLS enabled, forced, and a policy — a table without one fails the build |

## 31. Tamper-detection test

The proof that the audit layer works. Four scenarios, each asserting **detection**:

1. **Mid-chain modification** — alter a payload digest in record *n*; verification fails at *n*.
2. **Truncation** — delete the newest records past the last anchor; verification against the anchor
   fails.
3. **Wholesale rewrite** — recompute an entire tenant chain from record *k* forward so it is internally
   consistent; verification succeeds internally but **fails against the anchor chain**. This is the
   scenario plain chaining cannot catch and is the reason D20 chose anchoring.
4. **Anchor tampering** — alter one anchor record; the anchor chain's own entanglement fails at the next
   record.

Each scenario writes directly to the database as `adw_owner`, bypassing the application — because the
threat being modelled is exactly someone who can do that.

## 31b. Tenant-isolation test

The permanent adversarial suite required by `PRODUCT.md` §14. For every API route, every worker handler,
and every scheduled job: attempt access to tenant B's data while holding tenant A's context, and assert
zero rows and no error leakage. Plus: a transaction opened with no tenant context returns zero rows
rather than all rows.

## 31c. Scenario test — the proof criterion

`ARCHITECTURE.md` §37, in three parts:

1. **Drive execution `E-1042` end to end** using the scripted agent and canned tools: plan, six tasks,
   the deterministic gates, a **deliberate gate failure that triggers Rework 1 of 3**, a corrected second
   artifact version, and a human approval by an identity that is neither the requester nor any producer.
2. **Reconstruct it from the database alone** — a narrative of what was requested, what ran, what each
   gate checked, why rework happened, and who approved, produced with no running service and no access
   to the original inputs.
3. **Verify both chains, then tamper and confirm failure**, per §31.

---

## 32. Sequencing

Ten tasks. Each ends with something independently testable and committable.

| # | Task | Deliverable |
|---|---|---|
| 1 | Project skeleton, CI, lint, mypy strict | Build fails on a type error |
| 2 | `domain/` pure layer — ids, states, transitions, canonical, hashing, chain | Full unit coverage, no database |
| 3 | Database foundation — roles, RLS helper, migration policy test | Isolation provable on an empty schema |
| 4 | Tenant, definitions, execution, task models + task state machine | State machine tests pass |
| 5 | Audit chain — writer, `chain_head`, verifier | Chain appends and verifies |
| 6 | Anchor chain — writer, scheduler cadence, verifier | Tamper tests 1–4 pass |
| 7 | Action, evidence, redaction, KeyStore/BlobStore ports + dev adapters | Redaction-before-persist proven |
| 8 | Artifact, artifact definition, immutability enforcement | Immutability tests pass |
| 9 | Gate engine, gate decision, rework controller, approval service + SLA | Rework and SLA tests pass |
| 10 | Queue, dispatcher, worker loop, idempotency, scheduler | Scenario test §31c passes end to end |

**Definition of done for Phase 1:** all of §29–§31c green, `mypy --strict` clean, the isolation suite
green in CI, and the §31c narrative reconstructable from a database dump alone.

---

## 33. Open items, conflicts, and missing prerequisites

### 33.1 Proposed defaults for still-open Phase 1 decisions

Each is a working default so implementation is not blocked. Confirm or override.

| ID | Item | Proposed |
|---|---|---|
| **I** | Evidence inline vs blob threshold | 64 KiB |
| **P1** | Anchor cadence | 100 records per tenant or 300 seconds, whichever first |
| **P2** | `tenant_id` vs pseudonym in anchors | `tenant_id`; pseudonym deferred |
| **P5** | Scheduler placement | Leader-elected worker role via advisory lock |

### 33.2 Design rules this plan needs settled

Derived from accepted decisions, not new architecture — but each needs your sign-off.

| # | Rule | Basis |
|---|---|---|
| 1 | **Encryption boundary** — payload and free-text fields are ciphertext; identifiers, enums, timestamps, counts, and hashes stay plaintext so they remain queryable. Metadata therefore survives shredding | D1 already lists metadata residue as open |
| 2 | **KeyStore and BlobStore are ports with dev-only local adapters**; real KMS and object storage are deferred because the cloud provider is undecided | `PRODUCT.md` §26 #3 |
| 3 | **Phase 1 authentication is a dev-only stub** that establishes user, tenant, and role from a signed local token. OIDC is an external integration and is out of scope for this phase | The brief excludes external integrations |

**Rule 3 is the one to watch.** A stub authenticator that survives into a later phase is a severe
vulnerability. It must refuse to start unless the environment is explicitly `dev`, and that refusal must
itself be a test.

### 33.3 Conflicts and missing prerequisites found

| # | Finding | Severity | Resolution needed |
|---|---|---|---|
| 1 | **Python 3.13.x is installed; D16 specifies Python 3.12.** Proceeding on 3.13 would silently violate an accepted decision | **Blocking** | Install 3.12 for this project, or amend D16 deliberately |
| 2 | **Docker is not installed**, so testcontainers cannot provide the disposable PostgreSQL the integration and security suites need | **Blocking for tests** | Install Docker Desktop, or install PostgreSQL 16 locally and point tests at it |
| 3 | **`psql` is not on PATH** — no PostgreSQL client for migration inspection or manual verification | Medium | Install PostgreSQL client tools |
| 4 | **No CI exists**, while `mypy --strict`, dependency scanning, and the isolation suite are all accepted as build-failing gates | Medium | Task 1 creates the CI workflow |
| 5 | **`PRODUCT.md` §11 and §8.3 remain stale** — §11 fixes a six-tool set excluding `spreadsheet.write`, §8.3 lists G1–G5 with no workbook integrity gate | Low for Phase 1 | Amend before Phase 3, when tools are built |
| 6 | Older register items still unamended: `CLAUDE.md` §2 glossary, §4 threat model, §9/§11 stale lines; `DESIGN.md` §9.4/§15.2 render-time redaction | Low for Phase 1 | Amend when convenient |

Findings 1 and 2 block starting. The rest do not.

### 33.4 Deviation from the writing-plans skill

That skill's format requires literal code in every task step and saves to
`docs/superpowers/plans/`. This brief specifies a 31-section component document at
`docs/PHASE-1-IMPLEMENTATION-PLAN.md` and forbids writing code. The brief governs, so the skill's
file-structure mapping, task right-sizing, and no-placeholder discipline are applied, while its code
blocks and location are not. Task-level code belongs in the execution phase, once this plan is approved.
