# AI Digital Workforce

Production-grade platform where autonomous agents act as digital employees. A business user submits a
natural-language requirement; a Senior Agent decomposes it, delegates to specialized sub-agents, and
those agents perform **real business actions** against real systems — with every action recorded,
every artifact validated, and every claim backed by evidence.

This is not a chatbot and not a demo. Treat correctness, auditability, and least privilege as
functional requirements, not polish.

---

## 1. Conceptual Flow

```
User Requirement
  → Senior Agent (understand)
  → Execution Plan
  → Task
  → Sub-Agent
  → Skill
  → Tool
  → Action
  → Result
  → Artifact
  → Control Gate → PASS / FAIL
       ├─ FAIL → Rework → (re-enter at the failed Task)
       └─ PASS → Next Task
  → Final Review
  → Final Artifacts
  → Documentation
```

The Senior Agent / Orchestrator is responsible for, in order:

1. Understand the requirement.
2. Break it into tasks.
3. Assign tasks to specialized sub-agents.
4. Grant each agent only the tools and permissions that task needs.
5. Allow agents to perform real business actions.
6. Record every action.
7. Produce artifacts.
8. Validate artifacts through Control Gates.
9. Send failed work back for rework.
10. Verify that required actions actually happened.
11. Perform final review.
12. Generate final documentation.

Every one of those twelve steps must be observable in persisted state. If a step cannot be
reconstructed from the database after the fact, it did not happen in a way this platform accepts.

---

## 2. Terminology

Use these terms exactly, in code, in schemas, in the UI, and in conversation. Do not invent synonyms.

| Term | Meaning |
| --- | --- |
| **Agent** | A digital employee responsible for a business role. |
| **Agent Definition** | Configuration describing an agent's identity, role, instructions, skills, permissions, tools, inputs, outputs, and completion criteria. |
| **Skill** | A reusable capability / instruction set teaching an agent how to perform a class of work. |
| **Tool** | A capability letting an agent interact with an external system or execute an operation. |
| **Action** | A concrete tool invocation performed during an execution. |
| **Artifact** | A business work product produced or consumed by the system. |
| **Artifact Definition** | The schema/contract describing what an artifact must contain and how it is validated. |
| **Control Gate** | A mandatory validation checkpoint determining whether work may continue. |
| **Rework** | The controlled process triggered when a Control Gate fails. |
| **Evidence** | Information proving an action occurred, or that an artifact satisfies a requirement. |

**Agent** vs **Agent Definition**, and **Artifact** vs **Artifact Definition**, are the
instance/schema distinction. Keep them separate in the data model.

---

## 3. The Action Truth Model

This is the core integrity rule of the platform. The system must distinguish, as distinct persisted
states — never as a boolean:

- **planned** — the plan says this action should occur
- **attempted** — invocation started
- **executed** — the tool ran to completion
- **succeeded** — it ran and met its success criteria
- **failed** — it ran and did not
- **evidence** — the recorded proof of what actually happened

Hard rules:

- **Never claim an action was completed without execution evidence.** Not in an artifact, not in a
  status field, not in a report, not in the UI, and not in a message to the user.
- An agent's *assertion* that it did something is not evidence. Evidence is the recorded tool
  result: exit codes, response payloads, file hashes, row counts, screenshots, API receipts,
  external system IDs.
- Step 10 of the orchestrator flow ("verify that required actions actually happened") is a real
  verification pass over recorded evidence — it re-checks the world or the audit log, not the
  agent's self-report.
- **Agents must not approve their own work.** The producer of an artifact can never be the approver
  of the Control Gate covering it. Enforce this in code, not by prompt instruction.
- **Artifacts must be versioned; historical versions remain auditable.** Artifact updates are
  append-only new versions. Never mutate or delete a prior version.

The same discipline applies to *you*, Claude, when reporting on your own work in this repo — see
§8 Verification.

---

## 4. Security Principles

Non-negotiable, and they constrain design from day one:

- **Least privilege** — an agent gets the minimum tool set and scope for its task, granted per
  execution, not per agent globally.
- **Explicit permissions** — no implicit or inherited capability. If it isn't granted, it's denied.
- **Tenant isolation** — every query, every artifact, every log line is tenant-scoped. Isolation is
  enforced at the data layer, not only in application filters.
- **Authentication** and **authorization** — distinct concerns, both enforced server-side.
- **Audit logging** — every action, permission grant, gate decision, and artifact version is logged
  immutably.
- **Secure secret storage** — secrets live in a secret store, injected at the tool boundary.
- **Sandboxed code execution** — all agent-generated code runs in an isolated sandbox.
- **Tool-level permissions** — authorization is checked at the tool invocation site, every time.
- **Timeouts** and **resource limits** — on every tool call, sandbox run, and agent execution.
- **Input validation** and **output validation** — validate what enters a tool and what leaves it.

Two absolute prohibitions:

- **Never expose secrets to an LLM.** No credential, token, key, or connection string enters a
  prompt, a tool argument the model composes, a log the model reads, or an artifact. Tools resolve
  secret *references* internally; the model sees only the reference name.
- **Never allow arbitrary agent-generated code to execute directly on the host.** Python, SQL,
  shell, and browser automation all run sandboxed, with resource limits, a constrained filesystem,
  and an explicit network policy.

---

## 5. Capability Roadmap (future — do not build ahead of the current phase)

Agents will eventually be able to: read and modify Excel files; work with Google Sheets; execute
Python in a sandbox; create charts; generate documents, Markdown, and PDFs; work with databases;
call authorized external APIs; and perform browser-based actions where appropriate.

This list exists to inform architecture — the Tool abstraction must accommodate all of it — not to
license implementing any of it early.

---

## 6. Engineering Rules

- **Do not implement the entire platform at once. Work phase by phase.**
- **Plan before implementation.** Non-trivial work gets a written plan first.
- **Use tests.** Especially for state machines, gates, permissions, and validation.
- **Verify before claiming completion.**
- **Do not make unrelated changes.** No drive-by refactors, renames, reformatting, or dependency
  bumps outside the task.
- **Do not silently change architecture.** If the task requires an architectural change, stop and
  say so before making it.
- **Keep modules small and testable.**
- **Prefer explicit state machines for workflows.** Execution, Task, Control Gate, and Rework
  lifecycles are declared state machines with enumerated states and legal transitions — not
  implicit status strings mutated across the codebase.
- **Prefer deterministic validation where possible.** Schema checks, assertions, and computed
  comparisons before LLM judgment. Use an LLM as a validator only where determinism is genuinely
  unavailable, and record that the check was probabilistic.
- **Keep LLM provider-specific code behind an abstraction.**
- **Keep business logic independent from any specific LLM provider.** Orchestration, gates,
  permissions, and artifact handling must be testable with no live model.

---

## 7. Claude Code Workflow

```
PLAN → IMPLEMENT → TEST → VERIFY → REVIEW → REPORT → STOP
```

**Do not automatically proceed to another phase.** Finish the current phase, report, and stop.
Advancing is the user's call.

- Complex or multi-step work → use the appropriate Superpowers workflow (`brainstorming` for
  shaping requirements, `writing-plans` before code, `test-driven-development`, `executing-plans`,
  `systematic-debugging`, `verification-before-completion`, `requesting-code-review`).
- Frontend work → use the `impeccable` skill and follow `DESIGN.md`.
- Browser verification → use the `agent-browser` skill.

---

## 8. Verification

Before reporting any work as done:

- Run the tests and the build. Paste real output.
- If a check was not run, say it was not run.
- If tests fail, say so and show the failure.
- If part of the scope was skipped or blocked, name it explicitly.

"Should work", "this ought to pass", and "I've implemented X" without a run are all violations of
§3 applied to your own output. Evidence before assertions.

---

## 9. Frontend and Design

The frontend must read as a **premium enterprise SaaS product** — the kind of tool a compliance
officer, an operations lead, and a CTO all trust. It must **not** look like a generic AI-generated
interface.

**Avoid:** purple AI gradients; glowing effects; excessive glassmorphism; robot imagery; excessive
decorative icons; emoji-based UI; giant rounded cards; excessive animation; generic AI-chatbot
aesthetics.

**Use:** strong typography; excellent spacing; clear hierarchy; professional tables; timelines;
restrained color; functional icons; excellent data visualization; accessible components.

The interface's job is to make execution state legible: what was planned, what ran, what it
produced, what the gate decided, and what the evidence was. Dense, scannable, sortable, linkable.
Color carries meaning (state, severity, pass/fail) — never decoration.

**`DESIGN.md` is the visual source of truth once it exists.** Until then, the rules above govern,
and any frontend work should propose additions to `DESIGN.md` rather than accumulating undocumented
one-off styling.

---

## 10. Scope Discipline

- No application code is written until the phase calling for it is planned and agreed.
- Build for the current phase only. The roadmap in §5 informs interfaces; it does not authorize
  implementation.
- If a requirement here conflicts with something you're asked to do, say so before proceeding —
  don't silently resolve it in either direction.

---

## 11. Environment

- Windows; PowerShell is the primary shell (a Bash tool is also available — each takes its own
  syntax). Prefer cross-platform tooling and scripts in project code.
- Git repository; current branch `master`. No remote configured yet.
