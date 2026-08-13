# PRODUCT.md — AI Digital Workforce

Product truth for the platform. `CLAUDE.md` owns engineering and behavioral rules; `DESIGN.md` owns
the visual system; this document owns **what we are building, for whom, and what is in scope**.

Where this document and `CLAUDE.md` disagree on a principle, `CLAUDE.md` wins. Where they disagree on
scope, this document wins.

**Status:** foundational. Written before architecture, deliberately. Items marked **OPEN DECISION**
are unresolved and must not be silently assumed away — they are listed together in §26.

---

## 1. Product vision

Organizations run on work that is procedural, evidence-bearing, and repetitive — the monthly close,
the reconciliation, the compliance pack, the release checklist. That work is done by capable people
spending most of their time on assembly rather than judgment.

The AI Digital Workforce is a platform where an organization **hires, configures, and supervises
digital employees**: agents that hold a defined role, are licensed to use specific tools, perform
real work, and produce work products that a human reviews and signs.

The vision is not an assistant that answers questions. It is an operating system for delegated work,
in which every task has an owner, every action has a record, every deliverable has a version, and
every approval has a name attached to it. An organization should be able to point at a finished
deliverable and reconstruct exactly how it came to exist.

## 2. Product mission

Let a business user express a requirement in their own language and receive **verified, auditable
work product** — produced by a supervised team of agents, validated at mandatory checkpoints,
and accompanied by the evidence that proves it was actually done.

Three commitments define the product:

1. **Nothing is claimed without evidence.** A deliverable is only "done" when the record shows it.
2. **Nothing approves itself.** The producer of work is never its approver.
3. **Nothing is unexplainable.** Every figure, action, and verdict traces back to a source.

## 3. Target users

| User | What they do here | What they need |
|---|---|---|
| **Business Requester** — e.g. FP&A Analyst, Finance Manager | Submits a requirement in natural language; consumes the finished artifacts | Speed, clarity on progress, trust in the output |
| **Reviewer / Approver** — e.g. Financial Controller | Reviews artifacts at Control Gates; approves, rejects, or returns for rework | To see what changed, what it was checked against, and who produced it — fast |
| **Department Owner** — e.g. Head of FP&A, Engineering Manager | Configures the department: which agents exist, what they may do, what "good" looks like | Control over agent definitions, skills, gates, and materiality rules without engineering help |
| **Platform Administrator** — IT / Security | Manages tenancy, identity, integrations, secrets, permissions, budgets | Least-privilege enforcement, visibility, and hard limits |
| **Auditor / Compliance** — internal or external | Reads the record; verifies controls operated | Immutable, complete, exportable history with no write access |

Not target users at MVP: end consumers, individual practitioners, and developers building on the
platform via API.

## 4. User roles

Roles are the enforcement mechanism; users may hold several, subject to the separation-of-duties
constraint below.

| Role | Capabilities |
|---|---|
| `requester` | Create executions, view own executions and their artifacts, download deliverables |
| `reviewer` | Everything in `requester`, plus decide Control Gates within assigned departments |
| `department_owner` | Manage Agent Definitions, Skills, Artifact Definitions, gates, and thresholds for their department; view all departmental executions |
| `platform_admin` | Tenancy, users, roles, integrations, secret references, budgets, retention settings. **Cannot decide gates and cannot alter the audit record.** |
| `auditor` | Read-only across the entire tenant, including the audit log and every artifact version. No mutation of any kind. |

**Separation of duties (enforced in code, not policy):**

- The producer of an artifact — human or agent — can never be the approver of the gate covering it.
- A user cannot approve a gate on an execution they initiated, unless the tenant explicitly enables
  self-review for low-risk gates. **OPEN DECISION:** whether that exception exists at all.
- `platform_admin` is deliberately not a superset of `reviewer`. Administrative power and approval
  power are separated so that no single account can both configure a control and satisfy it.

## 5. Target organizations

Mid-market to enterprise organizations with a formalized back office and an audit exposure —
roughly 200–5,000 employees, with a finance function of 5+ people that already runs a defined
monthly cycle.

The qualifying characteristic is not size but **procedural maturity**: the organization already has
checklists, review steps, and named approvers. The platform digitizes a control structure that
exists; it does not invent one.

Poor fit: organizations without defined review processes, teams wanting an open-ended AI assistant,
and any use case where the work product does not need to survive scrutiny.

**OPEN DECISION:** the ideal customer profile is a hypothesis, not validated. Industry focus,
geography, and buyer (CFO vs COO vs CIO) remain to be confirmed through pilots.

## 6. Department concept

A **Department** is the packaging boundary for a business function. It is configuration and content —
never engine code.

A Department bundles:

- **Agent Definitions** — the roles that exist in this function
- **Skills** — the instruction sets those roles are trained in
- **Tool grants** — which tools this department's agents may be licensed to use
- **Artifact Definitions** — the deliverables this function produces and their validation contracts
- **Control Gates** — the checkpoints work must pass, and who may decide them
- **Policies** — materiality thresholds, approval requirements, budgets, retention

The platform engine is department-agnostic. Adding a Department must never require changing the
orchestrator, the state machines, the evidence model, or the console. If it does, the abstraction has
leaked and the design is wrong.

This is the load-bearing test of the architecture: **Finance and Mobile Development must be the same
engine running different Departments.** They differ in agents, skills, tools, artifacts, and gates —
never in how execution, evidence, or approval works.

Departments are tenant-scoped. A tenant may enable, disable, clone, and customize them.
**OPEN DECISION:** whether MVP departments are platform-curated only, or tenant-authorable.

## 7. Agent concept

An **Agent** is a digital employee: a named role with a job description, a scope of authority, a
licensed tool set, and a performance record.

The employment metaphor is deliberate and maps to real system objects:

| Employment concept | Platform object |
|---|---|
| Job description | Agent Definition |
| Training | Skill |
| Equipment and system access | Tool grant / permission |
| Assignment | Task |
| Work performed | Action |
| Deliverable | Artifact |
| Supervisor review | Control Gate |
| Personnel file | Execution history + audit log |

Two separations matter and must survive into the architecture:

- **Agent Definition vs Agent Runtime.** The Definition is durable, versioned configuration — what
  this role is. The Runtime is the ephemeral instance executing one Task under a specific permission
  grant. An execution pins the Definition version it ran against, so the record can always answer
  "what were this agent's instructions and permissions at the time?"
- **Skill vs Tool.** A Skill teaches *how* to do a class of work; a Tool is *the capability* to touch
  a system. A Skill never confers a Tool. Permission comes from the grant, never from instruction —
  otherwise an agent could talk its way into capability.

Agents are not autonomous employees. They are supervised ones: bounded by permission, budget, and a
gate they cannot decide.

> **Note for a later `CLAUDE.md` amendment:** §2's glossary does not yet define **Department** or
> **Agent Runtime**. Both are load-bearing here. Not edited in this change, per instruction.

## 8. First vertical: Finance

Finance is the **proving vertical**, not the product. It was chosen because its work is
artifact-heavy, its correctness is checkable deterministically, and its users already expect review
and evidence.

### 8.1 The MVP workflow — Monthly reporting & variance pack

**Requirement (as a user would state it):** *"Produce the March management reporting pack for the
UK entity — actuals versus budget by cost centre, with commentary on every variance above 5% or
£50k."*

**Inputs:** actuals export (XLSX/CSV), budget file (XLSX/CSV), optional prior-period pack and a
chart of accounts mapping.

**Output:** a report pack — an executive summary, a variance table, charts, and written commentary —
delivered as Markdown and PDF, with the underlying dataset as a versioned artifact.

### 8.2 The agent team

| Agent | Responsibility |
|---|---|
| **Engagement Lead** (Senior Agent / Orchestrator) | Understands the requirement, produces the Execution Plan, assigns tasks, runs final review |
| **Data Preparation Agent** | Parses and normalizes source files; maps accounts; flags structural problems |
| **Reconciliation Agent** | Verifies totals tie, periods align, and no accounts are unmapped |
| **Variance Analysis Agent** | Computes variances; identifies movements breaching materiality |
| **Commentary Agent** | Writes narrative explanation for each material variance |
| **Report Assembly Agent** | Produces the pack: structure, tables, charts, formatting |

### 8.3 The Control Gates

Gates are ordered, mandatory, and mostly deterministic — which is the point of choosing this workflow
first.

| Gate | Check | Type |
|---|---|---|
| **G1 · Input integrity** | Files parse; required columns present; period matches the request; no duplicate account rows | Deterministic |
| **G2 · Reconciliation** | Actuals total ties to the stated control total; budget total ties; zero unmapped accounts | Deterministic |
| **G3 · Variance completeness** | Every variance breaching the materiality threshold has commentary; no commentary exists for a variance that does not | Deterministic |
| **G4 · Narrative traceability** | **Every figure appearing in the narrative resolves to a value in the source dataset** | Deterministic |
| **G5 · Final review** | Controller reviews and signs the pack | **Human** |

G4 is the gate that earns the platform its claim. A written commentary containing a number that does
not exist in the data is the characteristic failure of language models applied to finance; it is also
mechanically detectable. Catching it deterministically, every time, and showing the check in the
record, is the difference between this product and a chat window.

### 8.4 Why this workflow

It exercises the entire spine — plan, delegate, act, produce, validate, rework, approve, document —
while touching no external system in write mode, requiring no code execution, and having a
correctness standard a controller can confirm in minutes.

## 9. Future verticals

Departments planned beyond Finance. None are in MVP scope; they are listed because the engine must be
shaped to accommodate them.

| Department | Representative agents | Representative artifacts | Why it stresses the platform |
|---|---|---|---|
| **Mobile Development** | Requirements Analyst, Implementer, Test Engineer, Reviewer, Release Manager | Specs, code changes, test reports, build artifacts, release notes | The vertical that forces sandboxed code execution, repository write access, and CI integration. It is the strongest test of the Tool abstraction and the correct second vertical for exactly that reason. |
| **HR** | Policy Analyst, Onboarding Coordinator, Compliance Checker | Policy documents, onboarding packs, compliance registers | Highest PII sensitivity; forces the data-classification model to be real |
| **Operations** | Process Analyst, Exception Handler, Reporting Agent | SOPs, exception reports, operational dashboards | High execution volume; stresses throughput and cost control |
| **Sales** | Proposal Writer, Pipeline Analyst, Quote Builder | Proposals, quotes, pipeline analyses | Forces CRM integration and external-facing document quality |
| **Marketing** | Campaign Analyst, Content Producer, Performance Reporter | Briefs, content drafts, performance reports | Weakest deterministic gates — forces the LLM-as-validator question to be answered properly |
| **Procurement** | Sourcing Analyst, Contract Reviewer, Vendor Assessor | RFP packs, comparison matrices, vendor assessments | Highest-stakes write actions; forces the approval model to mature |

**Mobile Development is the designated second vertical.** It is deliberately as unlike Finance as
possible, so that shipping it proves the Department abstraction rather than flattering it.

## 10. Core user workflow

1. **Submit.** The Requester describes the requirement in natural language and attaches inputs.
2. **Plan.** The Engagement Lead produces an Execution Plan — tasks, assigned agents, artifacts, and
   gates — shown to the Requester **before** work begins.
3. **Confirm.** The Requester confirms or adjusts the plan. This is the cheapest correction point in
   the system and the interface treats it as such.
4. **Execute.** Agents perform tasks. The console shows what is happening now, what has happened,
   and what each agent did — live, with evidence accumulating.
5. **Validate.** Each artifact meets its Control Gates. Deterministic gates decide instantly; human
   gates enter the Needs Attention queue.
6. **Rework.** A failed gate returns the task to its agent with the specific failure attached.
   Rework is visible in the record as a loop, never hidden as a retry.
7. **Approve.** The Reviewer sees the artifact, what it was checked against, who produced it, and
   what changed since the last version, then signs.
8. **Deliver.** Final artifacts are downloadable, versioned, and permanently reconstructible.
9. **Document.** The platform generates the execution documentation: what was requested, what was
   done, by whom, checked how, approved by whom.

The Requester's mental model should be **delegation to a team**, not prompting a model. The plan
confirmation step in (3) is what makes that true.

## 11. MVP scope

One tenant-facing vertical, one workflow, one deployment topology. Deliberately narrow.

**In scope:**

- **Platform core:** Execution, Task, Action, Evidence, Artifact + versions, Control Gate, Rework —
  as persisted state machines with the full six-state action truth model
- **One Department:** Finance, platform-curated
- **One workflow:** monthly reporting & variance pack (§8)
- **Six Agent Definitions**, versioned and pinned per execution
- **A fixed, deterministic tool set:** spreadsheet read, tabular transform, tabular compute, chart
  render, document render (Markdown → PDF), artifact read/write
- **Five Control Gates:** four deterministic, one human
- **Ingestion:** authenticated file upload (XLSX, CSV)
- **Operations console:** the eight questions from `DESIGN.md` §2, answerable end to end
- **Identity:** SSO via OIDC, with role assignment
- **Multi-tenancy** with database-enforced isolation, from the first commit
- **Immutable, tamper-evident audit log**
- **Cost controls:** per-execution and per-tenant budgets with hard stops
- **Redaction at ingest** before any evidence is persisted

**Deliberately limited within MVP:**

- **No agent-generated code execution.** The MVP ships a deterministic tool set instead of a Python
  sandbox. This removes the single largest security and infrastructure burden from v1, and aligns
  with `CLAUDE.md` §6's preference for deterministic validation. The trade-off is real and accepted:
  agents compose parameterized tools rather than writing code, which constrains what the Finance
  vertical can do. **The sandbox is the first post-MVP capability**, and the Tool abstraction is
  designed for it from the start.
- **Agent Definitions are platform-authored**, not tenant-editable.
- **One LLM provider**, behind the provider abstraction `CLAUDE.md` §6 requires.

## 12. Explicitly out of scope

Not in MVP. Listing them here is what makes the scope real.

**Capability:** agent-generated code execution and sandboxing · browser automation · direct database
access · external API write actions of any kind · email or message sending by agents · OCR and
document extraction · Google Sheets and live spreadsheet editing · scheduled or recurring executions
· agent-initiated escalation to other departments.

**Product:** any department other than Finance · any Finance workflow other than the variance pack ·
tenant-authored Agent Definitions, Skills, or Artifact Definitions · a public or partner API ·
white-labelling · marketplace or sharing of departments · mobile applications · offline use.

**Platform:** on-premise deployment · multi-region residency · SSO providers beyond OIDC · SCIM
provisioning · custom roles beyond the five in §4 · real-time collaborative editing of artifacts ·
localization and RTL support · billing and metering surfaces.

**Explicitly deferred, not rejected:** every item above is a candidate for a later phase. Nothing here
may be built early on the grounds that it is "small".

## 13. Deployment model

**Multi-tenant SaaS**, cloud-hosted, containerized, single region at MVP.

- One codebase, one deployment, all tenants.
- Single-tenant / dedicated-instance deployment stays a **supported future topology** — the
  architecture must not assume shared infrastructure in ways that foreclose it, because finance and
  regulated buyers will eventually demand it.
- On-premise is out of scope for MVP and is not designed for.
- Release model: continuous deployment behind feature flags; no tenant-specific code branches, ever.

**OPEN DECISION:** cloud provider and region, driven by §17 residency and the eventual customer base.

## 14. Tenancy model

Isolation is enforced **in the database**, not in application filters.

- Every tenant-owned row carries a `tenant_id`, and access is constrained by row-level security tied
  to the authenticated session's tenant. An application bug must not be sufficient to cross a tenant
  boundary.
- No query, view, job, or report may join across tenants. There is no "all tenants" read path outside
  a break-glass administrative procedure that is itself audited.
- Artifact blobs are stored under tenant-prefixed keys with per-tenant encryption keys, so that
  key destruction is a viable erasure mechanism (see §26, erasure).
- Every audit record, evidence record, and log line is tenant-scoped.
- Cross-tenant identifiers are never guessable or enumerable.
- Tenant isolation is tested adversarially — a permanent test suite that attempts cross-tenant access
  through every route and fails the build if any attempt succeeds.

This decision is recorded here rather than deferred because retrofitting tenancy touches every query
and every audit record, and is the least reversible choice in the system.

## 15. Expected scale

MVP planning assumptions. These are targets to design against, not measurements.

| Dimension | MVP assumption |
|---|---|
| Tenants | 5–20 pilot organizations |
| Users | 10–50 per tenant |
| Executions | 20–100 per tenant per month |
| **Load shape** | **Severely spiky.** Financial close concentrates the majority of monthly volume into the first five business days. Peak, not average, is the design target. |
| Concurrent executions | 20 per tenant, 100 platform-wide |
| Execution duration | 5 minutes to 2 hours |
| Tasks per execution | 5–30 |
| Actions per execution | 50–2,000 |
| Evidence records per execution | 100–10,000 |
| Input file size | up to 50 MB; up to 50 files per execution |
| Artifact versions retained | all, indefinitely within the retention window |
| Retention | 7 years assumed for financial records — **OPEN DECISION**, see §26 |

The spikiness matters more than the totals: a platform sized for average close-cycle load will fail
in the week that determines whether customers keep it.

## 16. Data sensitivity

Four classifications. Every artifact, evidence record, and field carries one.

| Class | Examples | Handling |
|---|---|---|
| **Public** | Product documentation, published policies | No restriction |
| **Internal** | Chart of accounts structure, department configuration | Tenant-scoped access |
| **Confidential** | Actuals, budgets, variance analysis, draft commentary, HR and vendor data | Role-restricted; access logged; never leaves the tenant boundary |
| **Restricted** | Credentials, API keys, tokens, personal data | **Never rendered, never sent to a model, redacted at ingest before persistence** |

**Unreleased financial results are material non-public information.** For any customer that is
listed, or preparing to be, pre-release actuals and commentary carry insider-trading sensitivity.
This raises access control and audit from good practice to legal exposure, and it is the reason the
`auditor` role is read-only and the reason every artifact view is itself an audited event.

Customer data is never used to train or improve any model. This must be contractual with the LLM
provider, not merely configured (§17).

## 17. Compliance assumptions

The platform is **built to SOC 2 and GDPR controls; no certification is claimed at MVP.**

- **SOC 2 trajectory:** access control, change management, audit logging, encryption, availability
  monitoring, and vendor management are implemented as if audited, so certification is achievable
  without redesign.
- **GDPR alignment:** lawful basis is the customer's; the platform is a **processor**. Requirements:
  data-processing agreement, subprocessor disclosure, data minimization, access and portability, and
  erasure — the last of which conflicts with append-only artifacts (§26).
- **The LLM provider is a subprocessor.** It must be disclosed to customers, covered by a DPA, and
  contractually bound to zero data retention and no training on customer data. A provider that cannot
  commit to this is not usable, regardless of model quality.
- **Residency:** configurable per deployment region. Single region at MVP.
- **Retention:** configurable per tenant, defaulting to the financial-records assumption in §15.
- Not assumed at MVP: SOX certification, HIPAA, PCI-DSS, FedRAMP, ISO 27001.

## 18. Human approval requirements

- **Every execution ends in a human gate.** In MVP, G5 (final review) is always human and cannot be
  disabled. A fully autonomous execution does not exist in this product.
- **Producer ≠ approver**, enforced in code. If the identities resolve to the same principal, the gate
  cannot be decided and the interface renders an integrity warning (`DESIGN.md` §11.5).
- **Approvals never expire into approval.** A human gate has an SLA — default 72 hours,
  tenant-configurable. On expiry the execution moves to an `Expired` state requiring explicit human
  action. **Timeout must never auto-approve, auto-reject, or silently proceed.** This closes the
  deadlock gap identified in the readiness report without introducing a worse failure.
- **Delegation** is explicit, time-boxed, and audited. A delegate's approval records both the delegate
  and the delegating authority.
- **Waivers** bypass a mandatory gate and are therefore governed harder than approvals: they require a
  role holding explicit waive permission, a written reason, and they surface permanently in the
  execution record and in the audit export. A waiver is never silent and never expires quietly.
- **Rejection** returns the task to rework with the specific failure attached, bounded by the rework
  limit in §25.
- **OPEN DECISION:** whether any gate may be configured as human-optional for low-risk departments,
  and who may configure that.

## 19. Supported artifact types

**MVP — produced:** Markdown documents · PDF documents · charts (SVG, PNG) · tabular datasets (XLSX,
CSV) · structured data (JSON) · the report pack (a composite artifact referencing the above).

**MVP — consumed:** XLSX · CSV · JSON.

**Post-MVP:** DOCX · PPTX · Google Sheets · source code and diffs · test and build reports · images ·
email drafts · database query results.

Every artifact type has an **Artifact Definition** — a schema and validation contract — before it may
be produced. An artifact type with no definition cannot pass a gate, because there is nothing to check
it against. Artifact Definitions are versioned, and an artifact records the definition version it was
validated against.

## 20. Required integrations

**MVP:**

| Integration | Purpose | Notes |
|---|---|---|
| **Identity provider (OIDC)** | SSO, user identity, role mapping | Identity must be external from day one — approval records need real, attributable humans |
| **LLM provider** | Agent reasoning | Behind the provider abstraction; zero-retention terms required |
| **Object storage** | Artifact and evidence blobs | Tenant-prefixed, per-tenant keys |
| **Email (platform-sent)** | Approval requests and execution notifications | **A platform function, not an agent action.** Agents cannot send email in MVP; the platform notifying a human about a pending approval is not an agent write to a business system, and the distinction is enforced in code. |

**Post-MVP:** Google Workspace (Sheets, Drive) · Microsoft 365 (Excel, SharePoint, Teams) · ERP
systems (NetSuite, SAP, Dynamics — **OPEN DECISION** on which first) · Slack/Teams notification ·
source control and CI (for the Mobile Development vertical) · SCIM provisioning · data warehouse
connectors.

## 21. Success criteria

**Product:**

- A Finance Manager completes a full monthly variance pack — requirement to signed artifact — without
  engineering assistance.
- The Controller approves the pack **using the platform's own evidence**, without re-deriving the
  numbers in Excel to check them. This is the real adoption test; anything less means the record is
  not trusted.
- ≥80% of executions reach final review with no human intervention before G5.
- Median time from requirement to approved pack materially below the customer's current baseline.
  **OPEN DECISION:** baseline unmeasured; the target number cannot be set honestly until pilots run.

**Integrity — these are pass/fail, not targets:**

- 100% of actions carry evidence appropriate to their terminal state.
- Zero incidents of success being displayed without linked evidence.
- Zero cross-tenant data exposures.
- 100% of executions fully reconstructible from persisted state after the fact.
- 100% of gate decisions carry an approver, a timestamp, and an artifact version.
- Zero instances of G4 (narrative traceability) passing a figure that is not in the source data.

**Platform:** a second department can be added without modifying the orchestrator, the state
machines, the evidence model, or the console. Until that is demonstrated, the Department abstraction
is unproven.

## 22. Non-functional requirements

| Attribute | Requirement |
|---|---|
| **Availability** | 99.5% monthly for the console; degraded execution is preferable to lost records |
| **Durability** | No acknowledged action, evidence record, artifact version, or gate decision is ever lost. Durability outranks availability everywhere they conflict. |
| **Console latency** | p95 < 300 ms for record views; live execution updates visible within 2 s of the event |
| **Execution throughput** | Peak close-week load (§15) without queue starvation; long executions must not block short ones |
| **Recoverability** | RPO ≤ 5 minutes, RTO ≤ 4 hours — **OPEN DECISION**, needs customer validation |
| **Resilience** | An LLM provider outage degrades gracefully: running executions pause and resume, they do not fail and lose work |
| **Observability** | Every execution traceable end to end by correlation ID across services |
| **Accessibility** | WCAG 2.2 AA, per `DESIGN.md` §16, verified in CI |
| **Browsers** | Current Chrome, Edge, Firefox, Safari. Desktop-primary per `DESIGN.md` §19 |
| **Time** | All timestamps UTC at rest, from a single trusted source; display timezone is a presentation concern |
| **Localization** | English only at MVP. Data model must not preclude localization; RTL support is **OPEN DECISION** |

## 23. Security requirements

Derived from `CLAUDE.md` §4 and the readiness report. Product-level statements; mechanisms belong to
architecture.

- **Redaction at ingest.** Secrets and Restricted-class data are removed **before** evidence and
  artifacts are persisted — never at render time. Because the record is immutable, anything stored is
  stored permanently; a redaction that only hides at display leaves the secret in the store forever.
- **Prompt injection is a first-class threat.** Every input an agent perceives — the requirement text,
  file contents, tool outputs, prior artifacts — is untrusted and may attempt to redirect the agent.
  Agent instructions and agent-perceived data must be separated, and no perceived content may expand
  permission, skip a gate, or alter a plan. This is the primary attack surface of the product.
- **Permission is granted per execution**, scoped to the task, time-boxed, and revoked at task end.
  No standing agent capability.
- **No secrets reach a model**, ever — not in prompts, tool arguments, logs, artifacts, or evidence.
- **No agent-generated code executes on a host.** MVP avoids this by shipping no code execution;
  the rule stands for when the sandbox arrives, with resource limits, filesystem constraints, and an
  explicit egress policy — egress being how exfiltration happens.
- **No cross-agent privilege borrowing.** A low-permission agent must not be able to induce a
  higher-permission agent or the orchestrator to act on its behalf.
- **Encryption** in transit and at rest, with per-tenant keys.
- **MFA** required for `reviewer`, `department_owner`, and `platform_admin`.
- **Break-glass access** is time-boxed, requires two-person authorization, and is itself audited.
- **Adversarial tenant-isolation tests** run permanently in CI (§14).

## 24. Audit requirements

The audit record is the product. If it is not trustworthy, nothing else matters.

- **Immutable and tamper-evident.** Append-only is not sufficient — a record an administrator can
  `UPDATE` is not an audit trail. Records are hash-chained so that alteration is detectable.
- **Complete.** Every action, permission grant, gate decision, artifact version, waiver, delegation,
  configuration change, and data access is recorded.
- **Attributed.** Every entry names the actor (agent identity or authenticated human), the tenant, the
  timestamp from a trusted source, and the version of every definition in force.
- **Reconstructible.** Any execution can be replayed as a narrative from persisted state alone,
  without the original files, the model, or any running service.
- **Auditable by outsiders.** The `auditor` role has full read access and no write path. Audit data is
  exportable in a machine-readable format for external review.
- **No privileged erasure.** No role, including `platform_admin`, can alter or delete audit records
  through the application. Retention expiry is the only removal path, and expiry is itself logged.
- **Auditability is not reproducibility.** The platform guarantees that what happened is recorded
  exactly; it does not guarantee that re-running the same requirement produces the same result,
  because agent reasoning is non-deterministic. This distinction is stated to customers plainly rather
  than blurred.

## 25. Cost-control requirements

Unbounded agent loops are both a spend risk and a correctness smell. Limits are hard stops, not
alerts.

| Control | MVP default | Behavior on breach |
|---|---|---|
| **Max rework loops per task** | 3 | Task blocks; escalates to Needs Attention for human decision |
| **Max tasks per execution plan** | 30 | Plan rejected at confirmation; Requester sees why |
| **Max tool calls per task** | 50 | Task fails with a recorded reason |
| **Max token spend per execution** | Tenant-configurable | Execution pauses at 100%, warns at 80%, requires human authorization to continue |
| **Max monthly spend per tenant** | Contractual | New executions blocked; running executions complete |
| **Max execution wall-clock** | 4 hours | Execution pauses and escalates |

Additional requirements:

- **Cost is visible per execution** in the console, and attributable per department, per agent, and
  per tenant. A cost that cannot be attributed cannot be controlled.
- **A breach never silently truncates work.** It pauses and escalates. Producing a partial artifact
  because the budget ran out, without saying so, would violate the platform's core claim.
- **Model tiering** — routing routine steps to cheaper models and reserving stronger models for
  judgment-heavy steps — is the primary cost lever. **OPEN DECISION:** whether MVP implements tiering
  or ships single-model and adds it later.

## 26. Open decisions

Unresolved. Each must be decided deliberately, not by whatever the first implementation happens to do.

| # | Decision | Why it matters | Blocks |
|---|---|---|---|
| 1 | **Erasure vs immutability** — how GDPR erasure is satisfied against append-only artifacts. Per-tenant key destruction (crypto-shredding) is the leading candidate and is why §14 mandates per-tenant keys. | Legal exposure; architecturally expensive to retrofit | Architecture |
| 2 | **Retention period** — 7 years assumed; needs legal confirmation per jurisdiction | Storage cost, erasure design, audit scope | Architecture |
| 3 | **Cloud provider and region** | Residency, cost, managed-service choices | Architecture |
| 4 | **Self-review exception** — may a requester ever approve their own execution's gate? | Separation of duties integrity | Data model |
| 5 | **Department authorship** — platform-curated only, or tenant-authorable, and when | Permission model, versioning, support burden | Data model |
| 6 | **Human-optional gates** — may any gate be configured without a human? | Core product promise | Data model |
| 7 | **Approval SLA default and escalation path** — 72h assumed; who is escalated to? | Deadlock behavior | Workflow design |
| 8 | **Model provider selection** and zero-retention contractual terms | Compliance blocker; provider is a subprocessor | Vendor decision |
| 9 | **Model tiering in MVP** — single model or tiered | Cost profile | Architecture |
| 10 | **Sandbox technology** for post-MVP code execution — the choice pulls on the deployment model even while deferred | Second-phase architecture | Architecture |
| 11 | **First ERP integration** for post-MVP writes | Roadmap sequencing | Roadmap |
| 12 | **ICP validation** — industry, geography, buyer | Product direction | Pilots |
| 13 | **Time-savings baseline** — unmeasured, so §21's target is unset | Success measurement | Pilots |
| 14 | **RPO/RTO targets** — 5 min / 4 h assumed, needs customer validation | Infrastructure cost | Architecture |
| 15 | **RTL and localization** — relevant if the initial market is MENA | Frontend architecture | Frontend design |
| 16 | **Materiality threshold defaults** for the Finance vertical — per-tenant configuration assumed | Department policy model | Department design |
| 17 | **Pricing and commercial model** — per seat, per execution, or per department | Metering requirements | Commercial |
