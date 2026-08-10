# DESIGN.md — Visual Design Constitution

The visual source of truth for the AI Digital Workforce platform. Binding on all frontend work.

`CLAUDE.md` owns engineering and behavioral rules. This document owns everything the user sees. Where
they touch — how the action truth model is rendered, how gate verdicts are displayed, how secrets are
never shown — this document defines the visual enforcement of the rule and `CLAUDE.md` defines the rule.

**Status:** authoritative from this commit. No UI is built ahead of the phase that calls for it.
Nothing here licenses building components now.

---

## 1. Thesis

**The Operations Record.**

This product's world is not the chat window. It is the audit ledger, the control record, the
laboratory notebook, the signed inspection form — instruments that exist so that later, someone can
prove what happened. Everything the platform does is a record: an action, its evidence, a verdict, a
version. The interface is that record, made live.

What this commits us to, concretely:

- **Rules, not containers.** Structure comes from hairline rules, aligned columns, and whitespace —
  not from boxing every group in a card. A card must earn its border; a rule almost never has to.
- **Tabular discipline.** Numbers, timestamps, durations, IDs, and counts align in columns and use
  tabular figures, everywhere, without exception. Columns that align are the single strongest signal
  that this product is serious.
- **Stamps for verdicts.** A Control Gate result is a stamp on a record: rectangular, bordered,
  uppercase, unambiguous, adjacent to what it judges and to who issued it.
- **Evidence is visible, not implied.** Every terminal state links to the thing that proves it.
- **Density is respect.** Operators live here for hours. Showing them more real information per
  screen is a service, not a compromise.

The product should read as though it were designed by people who expect to be audited. The quality
bar is Linear, Stripe, and Notion — their restraint, their typographic care, their refusal to
decorate — reached by our own route, not by imitating their surfaces.

**Anti-thesis.** If a screenshot of this product could be mistaken for a generic AI tool, the design
has failed regardless of how it scores on any other axis.

---

## 2. The Eight Questions

The interface exists to answer eight questions. Every screen is judged on whether it helps.

| # | Question | Answered by | Affordance requirement |
|---|---|---|---|
| 1 | What is happening? | Execution header — live status line | Current task, current agent, elapsed time, next gate. Visible without scrolling, on every execution surface. |
| 2 | What has happened? | Execution timeline | Complete, filterable, ordered event record. Never truncated without saying so. |
| 3 | What did the agents do? | Agent activity view | Per-agent lane: tasks assigned, actions taken, artifacts produced, permissions actually exercised. |
| 4 | What actions were executed? | Action ledger | Table: timestamp, agent, tool, target, lifecycle state, duration, result, evidence link. The audit surface. |
| 5 | What artifacts were created? | Artifact register | Name, type, version, producing agent, gate status, created, size. |
| 6 | Which control gates passed? | Gate strip + timeline stamps | Verdict, approver, timestamp, artifact version judged, rule applied. |
| 7 | Which failed? | Failure summary | Persistent, in the execution header. Failures are never only discoverable by scrolling. |
| 8 | What requires human attention? | Needs Attention queue | Globally reachable with a live count in the top bar. |

**Rules that follow from this:**

- Every one of the eight is answerable within two interactions from anywhere in the product.
- Questions 1, 7, and 8 are answerable **without leaving the current page**.
- No question is answered by a modal. Modals interrupt; the record persists.
- If a screen cannot help answer any of the eight, justify its existence before designing it.

---

## 3. Typography

### 3.1 Families

```
--font-sans: "Inter var", Inter, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
--font-mono: "JetBrains Mono", ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace;
```

One sans carries everything: headings, labels, buttons, body, and data. There is no display face.
Inter is used as a **UI text face**; it is never set above 30px and never used as a display voice.

Mono is used **only** for: identifiers, hashes, correlation/trace IDs, file paths, code, log output,
raw payloads, and durations. Mono as a costume for "technical" is prohibited.

Self-host both with `font-display: swap` and a preloaded Latin subset. No external font CDN.

### 3.2 Scale

Fixed rem, never fluid. Ratio ≈ 1.125–1.2.

| Token | Size | Line height | Use |
|---|---|---|---|
| `text-micro` | 11px / 0.6875rem | 16px | Column headers, stamp text, overline metadata. Uppercase, tracking +0.06em. |
| `text-xs` | 12px / 0.75rem | 16px | Captions, table secondary values, badge text, help text. |
| `text-sm` | 13px / 0.8125rem | 20px | **Compact body default.** Table cells, dense panels, form controls. |
| `text-base` | 14px / 0.875rem | 20px | **Comfortable body default.** Standard UI text. |
| `text-md` | 16px / 1rem | 24px | Prose, artifact descriptions, documentation body. |
| `text-lg` | 18px / 1.125rem | 26px | Panel titles (h4). |
| `text-xl` | 20px / 1.25rem | 28px | Section headings (h3). |
| `text-2xl` | 24px / 1.5rem | 30px | Page section headings (h2). |
| `text-3xl` | 30px / 1.875rem | 36px | Page title (h1). |

Nothing exceeds 30px. There is no display tier.

### 3.3 Weight, tracking, alignment

- Weights: **400** body, **500** labels/buttons/column headers/emphasis, **600** headings.
  700 is reserved for the single number in a stat readout. No other use.
- Tracking: `-0.011em` at 13–16px, `-0.018em` at 18–24px, `-0.024em` at 30px. Never below `-0.03em`.
  `+0.06em` on `text-micro` uppercase only.
- `text-wrap: balance` on headings; `text-wrap: pretty` on prose.
- Prose measure **68ch max**. Table and dense-UI content is exempt.
- Sentence case everywhere: headings, buttons, labels, menu items, table headers, empty states.
  Title Case and ALL CAPS appear only in `text-micro` contexts and gate stamps.
- Headings never end in a period. Body sentences always do.

### 3.4 Numerals — non-negotiable

```css
font-variant-numeric: tabular-nums;
font-feature-settings: "tnum" 1, "cv05" 1, "ss03" 1; /* tabular + open digits */
```

Applied to **every** numeric context: table numeric columns, timestamps, durations, counts, versions,
percentages, IDs, byte sizes, currency, chart axis labels, and stat readouts. A number that shifts
horizontally as it updates is a defect.

---

## 4. Color

Strategy: **Restrained.** A neutral gray ground, one deep ink-blue accent, and a reserved status
palette. Color is meaning. Color is never decoration.

Light is the default theme and the design reference. Dark is a fully specified peer theme with its
own selected steps — never an algorithmic inversion.

### 4.1 Neutrals

```
--gray-0:   #FFFFFF
--gray-25:  #FCFCFD
--gray-50:  #F7F8FA
--gray-100: #F1F3F6
--gray-200: #E3E6EB
--gray-300: #CFD4DC
--gray-400: #A5ACB8
--gray-500: #79818F
--gray-600: #59616E
--gray-700: #414954
--gray-800: #2C333C
--gray-900: #1B2128
--gray-950: #10151A
```

`gray-500` measures 3.93:1 on white — **it is not a body-text color.** Secondary text uses `gray-600`
(6.25:1). `gray-500` is legal only for disabled text, placeholder text at ≥14px, and non-text marks.

### 4.2 Accent — ink blue

```
--blue-50:  #EEF3FC     --blue-500: #2F6BC4
--blue-100: #DCE7F8     --blue-600: #1E55A8   ← primary
--blue-200: #B9CEF2     --blue-700: #17458A
--blue-300: #8DB3EA     --blue-800: #13376D
--blue-400: #4C7FD4     --blue-900: #102C55
```

`blue-600` on white = 7.19:1. White on `blue-600` = 7.19:1. `blue-300` on `gray-950` = 8.54:1.

The accent is used for exactly four things: **primary actions, current selection, focus rings, and
the "running / active" state.** Nothing else. It never tints a background for decoration, never
appears as a gradient, and never carries an illustration.

### 4.3 Status palette — reserved

These hues are reserved. They never appear as chart series, never as decoration, never as brand.

| Role | Light text/mark | Light tint bg | Dark text/mark | Meaning |
|---|---|---|---|---|
| Neutral | `#414954` | `#F1F3F6` | `#A5ACB8` | Planned, queued, draft, not run, cancelled, superseded |
| Active | `#17458A` | `#EEF3FC` | `#8DB3EA` | Running, attempted, in progress, current version |
| Success | `#12683D` | `#EAF6EF` | `#5FBF8A` | Succeeded, passed, verified |
| Attention | `#7E4E00` | `#FDF3E3` | `#D9A441` | Awaiting human, rework, waived, partial, unverified |
| Failure | `#94201A` | `#FDEDEB` | `#F0837A` | Failed, blocked, rejected, gate FAIL |

Base marks (for dots, borders, chart status encoding): success `#1A7F4B`, attention `#9A6100`,
failure `#B42318`. All ≥5:1 on white.

Every tinted badge measures ≥6:1 text-on-tint in light and ≥6.6:1 in dark. Verified.

**Color is never the sole carrier of status.** Every status renders as glyph + color + text label.

### 4.4 Surfaces

| Token | Light | Dark | Use |
|---|---|---|---|
| `surface-base` | `#F7F8FA` | `#10151A` | App background |
| `surface-raised` | `#FFFFFF` | `#171D24` | Panels, tables, content |
| `surface-overlay` | `#FFFFFF` | `#1E252E` | Menus, popovers, modals, tooltips |
| `surface-sunken` | `#F1F3F6` | `#0B0F13` | Wells, code blocks, inset detail rows |
| `surface-nav` | `#FFFFFF` | `#0D1216` | Side nav and top bar — one step apart from content |

### 4.5 Text

| Token | Light | Dark | Contrast |
|---|---|---|---|
| `text-primary` | `#1B2128` | `#EFF1F4` | 16.2:1 |
| `text-secondary` | `#59616E` | `#A5ACB8` | 6.25:1 / 8.03:1 |
| `text-tertiary` | `#79818F` | `#8B93A1` | Non-body use only |
| `text-disabled` | `#A5ACB8` | `#59616E` | Paired with `aria-disabled` |
| `text-on-accent` | `#FFFFFF` | `#FFFFFF` | 7.19:1 on `blue-600` |

### 4.6 Borders

| Token | Light | Dark | Use |
|---|---|---|---|
| `border-subtle` | `#E3E6EB` | `#232A33` | Table row rules, internal dividers |
| `border-default` | `#CFD4DC` | `#2E3742` | Panel edges, input borders, card edges |
| `border-strong` | `#A5ACB8` | `#414954` | Input hover, emphasized separation |
| `border-accent` | `#1E55A8` | `#8DB3EA` | Selection, focus, active tab |

### 4.7 Prohibited color moves

Gradients of any kind on UI chrome. Purple as an accent or state color. Neon or fully saturated
hues. Glows, colored halos, and colored drop shadows. Colored backgrounds behind large regions for
decoration. Dark mode produced by CSS filter inversion. Status hues used as chart series colors.
Color-only encoding of any state.

---

## 5. Spacing, Layout, Density

### 5.1 Scale

4px base. Use the scale; no arbitrary values.

```
space-0: 0     space-4: 16px   space-12: 48px
space-px: 1px  space-5: 20px   space-16: 64px
space-1: 4px   space-6: 24px   space-20: 80px
space-2: 8px   space-8: 32px   space-24: 96px
space-3: 12px  space-10: 40px
```

Rhythm rules:

- **More space above a heading than below it.** Standard pairing: `space-8` above, `space-3` below.
- Tight within a group, generous between groups. A label sits `space-1` from its value; two groups
  sit `space-6` apart.
- One vertical rhythm per surface. Do not mix two spacing systems on one page.

### 5.2 Layout

- Side nav: 240px expanded, 56px icon rail. Top bar: 48px.
- Content max width: prose 68ch; forms 640px; tables and timelines full-bleed within their region.
- Detail pane (right): 400px default, 480px for artifact previews, resizable and persisted.
- Page gutters: `space-6` at ≥1280px, `space-4` at ≥768px, `space-3` below.
- Design target: **1440×900**. Verify at 1280 and 1920.

### 5.3 Density

Two density modes, set by `data-density="compact|comfortable"` on the root. **Compact is the
default.** Density is a token layer — components never hard-code these values.

| Token | Compact | Comfortable |
|---|---|---|
| `row-height` | 32px | 40px |
| `cell-padding` | 8px 12px | 12px 16px |
| `control-height-sm` | 24px | 28px |
| `control-height-md` | 28px | 32px |
| `control-height-lg` | 32px | 36px |
| `body-size` | 13px | 14px |
| `stack-gap` | 8px | 12px |
| `section-gap` | 24px | 32px |

Coarse pointers (`@media (pointer: coarse)`) force comfortable and 44px minimum targets.

---

## 6. Borders, Radii, Elevation

### 6.1 Borders

1px hairline is the primary structural device. 2px exists only for focus rings and the active-tab
indicator. Nothing is thicker.

Dashed borders are legal in exactly one place: the file dropzone.

Colored left/right accent borders on cards, list items, callouts, and alerts are prohibited above 1px.

### 6.2 Radii

```
radius-none: 0      radius-md: 6px    radius-full: 9999px
radius-sm:  3px     radius-lg: 8px
```

- `radius-sm` — buttons, inputs, badges, stamps, chips, checkboxes
- `radius-md` — panels, menus, popovers, tooltips, dropzones
- `radius-lg` — modals and drawers. **This is the ceiling.** Nothing in this product has a radius
  above 8px.
- `radius-full` — avatars and status dots only

### 6.3 Elevation

**Declare elevation once: border or shadow, never both.** A 1px border under a soft shadow is the
ghost card.

- Panels, tables, cards, wells → **border only**, no shadow.
- Floating overlays → **shadow only**, no border.

```
--shadow-popover: 0 1px 2px rgb(16 21 26 / .05), 0 4px 12px -3px rgb(16 21 26 / .10);
--shadow-overlay: 0 1px 2px rgb(16 21 26 / .06), 0 8px 24px -6px rgb(16 21 26 / .14);
--shadow-modal:   0 2px 4px rgb(16 21 26 / .06), 0 24px 48px -12px rgb(16 21 26 / .20);
```

Dark theme uses the same geometry at higher opacity plus a 1px `#2E3742` top edge on overlays,
because shadow alone does not separate on a dark ground.

Every shadow carries an offset and a blur. Zero-offset halos, hard block shadows, and colored
shadows are prohibited.

---

## 7. Iconography

**Lucide**, 1.5px stroke, `currentColor` only. Never filled variants. Never multicolor. Never mixed
with another icon set.

Sizes: **16px** in dense UI and inline with text; **20px** standalone or in empty states; **24px**
only in the top bar. Nothing larger — there are no hero icons in this product.

Rules:

- An icon must denote an **action**, an **object type**, or a **status**. If it does none of those,
  delete it.
- Never decorate a heading with an icon. Never place an icon inside body prose.
- Never use an icon as an illustration substitute in an empty state.
- One meaning per icon, one icon per meaning, product-wide.
- Icon-only buttons require `aria-label` and a tooltip.
- Emoji and Unicode glyphs are prohibited as icons, in labels, in status, in notifications, and in
  generated artifacts.
- **No robot, brain, sparkle, wand, or magic imagery anywhere.** Agents are employees, not robots.

### 7.1 Domain vocabulary

| Concept | Icon | Concept | Icon |
|---|---|---|---|
| Execution | `route` | Artifact | `file-text` |
| Execution Plan | `list-checks` | Artifact Definition | `file-cog` |
| Task | `list-todo` | Control Gate | `shield-check` |
| Agent | `circle-user-round` | Gate passed | `circle-check` |
| Agent Definition | `user-round-cog` | Gate failed | `circle-x` |
| Skill | `book-open-text` | Rework | `rotate-ccw` |
| Tool | `wrench` | Evidence | `file-check` |
| Action | `activity` | Audit log | `scroll-text` |
| Sandbox execution | `terminal` | Permission | `key-round` |
| Needs attention | `circle-alert` | Tenant | `building-2` |
| Version history | `history` | Blocked | `ban` |

Lucide has renamed several icons (`alert-circle` → `circle-alert`, `loader-2` → `loader-circle`,
`bar-chart-3` → `chart-column`). Verify names against the installed version and pin it.

---

## 8. Buttons

### 8.1 Variants

| Variant | Fill | Border | Text | Use |
|---|---|---|---|---|
| Primary | `blue-600` | none | white | The one action this view exists for |
| Secondary | `surface-raised` | `border-default` | `text-primary` | Standard actions |
| Ghost | transparent | none | `text-secondary` | Toolbar, table row, and tertiary actions |
| Danger | `#B42318` | none | white | Irreversible destructive actions |
| Danger subtle | transparent | `#B42318` | `#94201A` | Destructive actions in dense contexts |
| Link | none | none | `blue-600` | Inline navigation only |

**One primary button per view region.** Two primaries means the hierarchy is undecided.

### 8.2 Anatomy and states

- Height from `control-height-*`. Horizontal padding `space-3`; icon-to-label gap `space-2`.
  Icon-only buttons are square at the control height.
- `radius-sm`. Weight 500. Sentence case. No full-width buttons except in drawers and below 640px.
- Required states, all of them: `default`, `hover`, `focus-visible`, `active`, `disabled`, `loading`.
  - Hover: one step darker fill (primary) or `gray-50` (secondary/ghost).
  - Active: two steps darker, no transform, no scale.
  - Disabled: `gray-100` fill, `text-disabled`, `cursor: not-allowed`, `aria-disabled="true"`.
    Never remove a disabled button from the tab order without an accessible explanation of why it
    is disabled.
  - Loading: `loader-circle` replaces the leading icon and spins; **the label stays**; width is
    locked to prevent reflow; `aria-busy="true"`; the button is not interactive.

### 8.3 Destructive and real-world actions

Actions that touch external business systems — sending mail, writing to a database, calling a
customer API, publishing a document, granting a permission — are not ordinary buttons.

- They are visually distinguished (danger variant or an explicit confirmation step).
- Irreversible actions require **typed confirmation** of the object name, not a bare "Are you sure?".
- The confirmation surface states, in the product's own words: what will happen, to which system,
  under which agent identity, and whether it can be undone.
- After invocation, the button reflects **server-confirmed state only** (see §14.4).

---

## 9. Forms

### 9.1 Structure

Order, always: **label → optional description → control → validation message**. The validation
message replaces the description in the same slot; the field never changes height on error.

- Labels are always visible, always above the control, weight 500, `text-xs`.
  **Placeholder-as-label is prohibited.**
- Placeholders show format examples only (`2026-03-14`), never instructions, never the label.
- Required fields carry the word **Required** in the label row. An asterisk alone is not sufficient.
  When most fields are required, mark the optional ones instead.
- Field width matches expected content. A date input is not 100% wide. Full-width inputs are for
  free text only.
- Group related fields in `fieldset`/`legend`. Sections separated by a hairline rule and `space-8`.

### 9.2 Controls

Native semantics wherever possible: `input`, `select`, `textarea`, `button`, `fieldset`. Custom
controls only where HTML cannot express the interaction (combobox, date range, permission tree), and
then built to the WAI-ARIA Authoring Practices pattern with full keyboard support.

- Border `border-default`; hover `border-strong`; focus per §16.2; error `#B42318` at 1px.
- Height from `control-height-md`. Padding `space-2 space-3`.
- Checkbox and radio at 16px with a 24px hit area minimum.
- No custom scrollbars, no custom select chevrons that break platform behavior, no invented
  affordances for standard tasks.

### 9.3 Validation

- Validate on **blur** and on **submit**. Never on every keystroke, except live-formatting fields
  (currency, phone) and availability checks, which are debounced ≥400ms.
- Error message names the problem **and** the fix: "Deadline must be after the start date" — not
  "Invalid date". Never blame the user.
- `aria-invalid="true"` plus `aria-describedby` pointing at the message.
- On failed submit: an error summary at the top of the form, focus moved to it, each item a link to
  its field. The summary states the count.
- Server validation is authoritative and its errors render in the same slots as client errors.

### 9.4 Secrets and permissions — visual enforcement

These are design requirements, not suggestions. They implement `CLAUDE.md` §4.

- **A stored secret value is never rendered.** Not masked, not partially revealed, not on hover, not
  in a "reveal" affordance. A configured secret displays as: name, `Set`, last-updated timestamp,
  and a `Replace` action. There is no read path in the UI.
- Secret inputs are write-only, `autocomplete="off"`, excluded from form state logging, and cleared
  on navigation.
- Any surface that could echo a secret — log viewers, action payloads, error details, artifact
  previews — renders redactions as `••••••` with the key name beside it, and the redaction happens
  server-side. The client never receives the value it is hiding.
- **Permission grants are shown explicitly, never as a preset.** A permission selector lists every
  individual capability with its scope, in plain language, with the tool it belongs to. A dropdown
  labeled "Standard access" that hides its contents is prohibited.
- Escalation requests render as a Needs Attention item showing: requesting agent, requested
  capability, scope, justification, requested duration, and the task it serves.

---

## 10. Tables

Tables are the primary surface of this product. They get the most care.

### 10.1 Structure

- Real `<table>` semantics: `thead`, `tbody`, `th` with `scope`, `caption` (visually hidden when the
  surrounding heading already names it).
- Full-bleed within its panel. Hairline `border-subtle` row rules. **No zebra striping** — striping
  compensates for poor alignment, and our columns align. **No vertical grid lines** below 8 columns.
- Header: sticky, `text-micro` uppercase, weight 600, `text-secondary`, on `surface-raised` with a
  1px `border-default` bottom edge. Never a filled gray header block.
- Row height from `row-height`. Single-line rows by default; overflow truncates with ellipsis and
  exposes the full value in a title/tooltip.
- First column is the record identifier and is a link to the record. It is sticky on horizontal scroll.
- Numeric, duration, and byte columns are **right-aligned** with tabular figures. Timestamps are
  left-aligned with tabular figures. IDs are mono at `text-xs`.

### 10.2 Behavior

- **Sorting:** click the header; `aria-sort` on the active column; a 12px `chevron-up`/`chevron-down`
  after the label. Sort is server-side and reflected in the URL.
- **Selection:** leading checkbox column, header checkbox for select-all-on-page, an explicit
  "Select all N matching" affordance when a filter is active. Selected rows take a `blue-50` tint —
  not a thick left border. A selection action bar appears in place of the table toolbar, stating the
  count.
- **Row actions:** right-aligned. Visible on `hover` and on `focus-within`, plus an always-visible
  overflow menu (`ellipsis-vertical`). **Hover-only actions are prohibited** — they are invisible to
  keyboard and touch.
- **Filters:** one row above the table, left-aligned, as chips that state the active constraint.
  Filter state lives in the URL and is shareable.
- **Pagination:** cursor-based. Footer reads `1–50 of 1,284` with tabular figures, page-size
  selector, and previous/next. Infinite scroll is prohibited on audit surfaces.
- **Column configuration** is persisted per user. Default visible columns max out at 8.
- **Expandable rows** open a full-width detail row inset by `space-8` with a left hairline rule.
  Nested tables are prohibited.
- Horizontal overflow scrolls **inside the table container**. The page never scrolls horizontally.
- Virtualize above 200 rows; keep row height fixed so the scrollbar tells the truth.

### 10.3 Required table states

`loading` (skeleton rows matching the real row height and column count — never a centered spinner),
`empty`, `filtered-empty`, `error`, `partial` (some rows failed to load, stated explicitly).

---

## 11. Status System

### 11.1 The three-part rule

Every status renders as **glyph + color + text label**. Always all three. A colored dot alone, a
colored row alone, or a colored badge with no text are all prohibited.

### 11.2 Forms

- **Badge** — in tables and lists. `radius-sm` rectangle, 1px border in the status hue at 30%
  weight, tinted background, `text-xs` weight 500 sentence-case label, 12px leading glyph. Height
  20px compact / 24px comfortable. **Not a pill** — pills read consumer; the ledger uses rectangles.
- **Dot** — 6px circle, only inside already-labeled contexts such as a legend or a nav item.
- **Stamp** — Control Gate verdicts only. See §11.5.
- **Banner** — page-level state. Full-width, 1px border, tinted background, `space-3` padding,
  a 16px glyph, a one-line statement, and at most one action. Never dismissible when it reports a
  failed or blocked state.

### 11.3 The action truth model, rendered

`CLAUDE.md` §3 defines six distinct action states. The UI renders them as six distinct things and
**never collapses them**.

| State | Badge | Glyph | Meaning shown to the user |
|---|---|---|---|
| Planned | Neutral | `circle-dashed` | In the plan. Not started. |
| Attempted | Active | `circle-dot` | Invocation started. Outcome unknown. |
| Executed | Active | `circle-dot` | Ran to completion. Success not yet assessed. |
| Succeeded | Success | `circle-check` | Ran and met its criteria. **Evidence linked.** |
| Failed | Failure | `circle-x` | Ran and did not meet its criteria. Error linked. |
| Unverified | Attention | `triangle-alert` | Reported complete, no execution evidence recorded. |

**Hard rules:**

- A green check renders **only** for `Succeeded` **with a resolvable evidence link**. Success styling
  without evidence is a defect, not a display choice.
- An agent's self-report with no evidence renders as **Unverified**, in the attention hue, with the
  words "Reported, not verified". It is never shown as success.
- Every terminal state links to its evidence: the tool result, exit code, response payload, file
  hash, row count, screenshot, or external system ID.
- Aggregate counts state their basis: "8 of 12 verified" — never a bare "8 complete".

### 11.4 Domain state vocabulary

| State | Hue | Glyph | Applies to |
|---|---|---|---|
| Draft | Neutral | `file-pen` | Plan, artifact |
| Queued | Neutral | `circle-dashed` | Task, action |
| Running | Active | `loader-circle` | Execution, task, action |
| Awaiting approval | Attention | `user-round-check` | Gate, task |
| Rework | Attention | `rotate-ccw` | Task |
| Waived | Attention | `shield-alert` | Gate — always shows reason and approver |
| Passed | Success | `circle-check` | Gate, task |
| Completed | Success | `circle-check` | Execution, task |
| Failed | Failure | `circle-x` | Anything |
| Blocked | Failure | `ban` | Task, execution |
| Cancelled | Neutral | `circle-slash` | Execution, task |
| Superseded | Neutral | `history` | Artifact version |

One vocabulary product-wide. A state means the same thing and looks the same everywhere it appears.

### 11.5 Gate stamps

A Control Gate verdict is the most consequential thing the interface displays. It gets its own form.

- Rectangular, `radius-sm`, 2px border in the verdict hue, tinted background, label in
  `text-micro` uppercase weight 600 with +0.06em tracking: **PASS** / **FAIL** / **WAIVED**.
- A stamp never appears alone. It is always accompanied, in the same block, by:
  **who or what approved it** (agent ID or human name — never blank), **when** (absolute timestamp),
  **which artifact version** it judged, and **which rule** produced the verdict.
- The approver line renders the producer/approver distinction visibly. If producer and approver
  resolve to the same identity, the UI renders a Failure-hue integrity warning — the platform
  forbids self-approval, and the interface says so rather than hiding it.
- Deterministic and LLM-assisted verdicts are visually distinguished. An LLM-assisted verdict carries
  the label "Model-assessed" and links to its reasoning. It is never presented with the same
  finality as a deterministic check.

---

## 12. Timelines

Two forms. Both are records, not decorations.

### 12.1 Execution timeline (vertical)

The primary answer to "what has happened".

- A single 1px `border-subtle` rail at a fixed left offset. Event nodes are 8px circles on the rail,
  filled in the status hue, with a 2px `surface-raised` ring so they read against the rail.
- Three columns: **timestamp** (mono, `text-xs`, tabular, fixed width) · **rail** · **content**.
- Event row: title (weight 500), actor (agent name, `text-secondary`), and a collapsed detail
  disclosure. Expanded detail shows the action payload, result, duration, and evidence links in a
  `surface-sunken` well.
- Grouped by task. Task group headers break the rail with a full-width hairline and the task name.
- **Gate verdicts break the rail**: a full-width stamp row with a top and bottom hairline. This is
  the timeline's punctuation and the only place its rhythm is interrupted.
- **Rework renders as a visible return**: a labeled connector from the failing gate back to the task
  it reopened, with the loop iteration count ("Rework 2 of 3"). Rework is never hidden as a retry.
- Default order newest-first, toggleable, with the choice persisted.
- Filter by agent, task, event type, and outcome. Active filters state how many events are hidden.
- Live executions append at the head. New events fade in over 120ms and **never move scroll position
  or focus**. When the user has scrolled away from the head, a "N new events" affordance appears
  instead of auto-scrolling.

### 12.2 Plan timeline (horizontal)

The execution plan and task schedule.

- Rows are tasks; bars are duration; bar fill is the status hue; the bar carries the task name inside
  it when it fits, beside it when it does not.
- Dependency links are 1px `border-strong` connectors with a small arrowhead. No curves, no glow.
- A 1px `blue-600` "now" line on live executions.
- Time axis with tabular labels at the top, sticky.
- Gates appear as narrow stamp markers on the row they gate.

### 12.3 Time display rules

- **Absolute timestamps are always available.** Relative time ("3 min ago") may lead, but the
  absolute value with timezone is in the `title` and in the expanded detail.
- One timezone across the product, named in the UI, user-switchable, defaulting to the tenant's.
- Format `2026-03-14 09:41:07 UTC`. ISO-ordered, tabular, unambiguous. Never locale-ambiguous
  numeric dates.
- Durations in mono: `1m 04s`, `2h 17m`. Sub-second as `840ms`.

---

## 13. File Uploads

- **Dropzone:** `radius-md`, 1px dashed `border-default`, `surface-sunken` background, height ~120px
  compact. Contents: a 20px `upload` icon, one primary line ("Drop files or browse"), one constraint
  line ("XLSX, CSV, PDF, DOCX · 25 MB max"). No illustration. Never taller than 160px.
- The browse control is a real `<button>` triggering a real file input. A dropzone alone is not
  keyboard-accessible and is never shipped alone.
- Drag-over state: `border-accent`, `blue-50` background. No scale, no glow.
- Paste-to-upload and OS drag are both supported.

**Per-file row** (a table, not a card list): type icon · filename (middle-truncated, extension
always visible) · size · progress · status · remove.

- Upload progress is **determinate** — bytes transferred is a real denominator.
- Post-upload pipeline states are shown explicitly and separately, because they are distinct real
  events: `Uploaded` → `Scanning` → `Parsed` → `Indexed`. Each can fail independently with its own
  message and retry.
- Client-side validation of type and size before upload; server validation is authoritative and its
  rejections render on the same row.
- A rejected file stays in the list with its reason until dismissed. Files never disappear silently.

---

## 14. Artifact Previews

### 14.1 Artifact header

Every artifact, everywhere it appears, carries the same header: type icon · name · version chip
(`v3 · Current` or `v2 · Superseded`) · producing agent · created timestamp · size · gate status
badge. Actions: `Open`, `Download`, `Compare versions`, `View evidence`.

### 14.2 Preview by type

| Type | Surface |
|---|---|
| Spreadsheet / table | Virtualized grid with column letters and row numbers, frozen header, sheet tabs, cell selection with the raw value shown in a status strip |
| Document / Markdown | Rendered at 68ch measure on `surface-raised`, with a source toggle |
| PDF | Embedded viewer, page navigation, page count, text selection |
| Chart | Rendered SVG plus a mandatory "View data" toggle to the underlying table |
| Structured data (JSON/XML) | Mono, line numbers, collapsible nodes, path breadcrumb |
| Code | Mono, line numbers, restrained syntax highlighting drawn from the categorical palette |
| Image | Contained, with dimensions and a zoom control |
| Unknown | Metadata table and download only. Never a broken preview. |

### 14.3 Versioning — required, not optional

- The version history panel is **part of the artifact surface**, not a hidden menu item. It lists
  every version with: version number, producing agent, timestamp, gate verdict, and a diff link.
- Prior versions are always openable and render read-only behind a persistent Neutral banner:
  "Version 2 · Superseded on 2026-03-14 09:41 UTC · Read only". The banner is not dismissible.
- Diff views: side-by-side for text and Markdown; cell-level highlight for sheets; field-level for
  structured artifacts. Additions in Success hue, removals in Failure hue, both also marked with
  `+`/`−` so the diff survives colorblindness and printing.

### 14.4 Safety in preview

- Artifact content is **never** rendered as live HTML in the application origin. Documents render
  sandboxed; scripts never execute; external resource loading is blocked.
- Nothing in an artifact preview auto-plays, auto-executes, or auto-fetches.
- Download is always available, even when preview fails.
- Redaction happens server-side. A preview never receives content it is expected to hide.

---

## 15. Loading, Error, and Empty States

### 15.1 Loading

- **Skeletons for content**, shaped like the real thing: the real row height, the real column count,
  the real panel geometry. Neutral `gray-100` blocks with a 1.2s shimmer, or no shimmer under
  reduced motion. Never a centered spinner over a content region.
- **Spinners only** inside buttons and for full-surface transitions under 400ms.
- **Determinate progress bars only when the denominator is real** — bytes uploaded, N of M tasks
  complete, page X of Y. A progress bar for work of unknown duration is a lie and is prohibited.
- **Long-running agent work** shows a live status line, not a spinner: current task, current agent,
  current tool, elapsed time (mono, ticking), and the last recorded event. The event feed is the
  progress indicator.
- **Stale data is announced.** When polling or the event stream drops, a Neutral chip reads
  "Last updated 14:02:11 · Reconnecting". Numbers are never shown as live when they are not.
- **Optimistic UI is prohibited for anything representing a real business action.** The interface
  renders server-confirmed state only. This is the visual half of "never claim an action was
  completed without execution evidence".

### 15.2 Errors

Three tiers, chosen by blast radius:

1. **Field** — inline, below the control, Failure hue, 12px `circle-alert`, `aria-describedby`.
2. **Region** — an inline panel replacing the failed content: what failed, why if known, what to do,
   a retry action, and the correlation ID in mono with a copy button.
3. **Page** — full-surface, navigation and shell retained so the user is never stranded.

Rules:

- **Toasts are for transient confirmations only.** Never for errors, never for anything the user must
  act on, never for anything auditable. An error that vanishes is an error that was never reported.
- **Agent and tool failures are domain events, not UI errors.** They render in the execution record
  as a Failed action with error payload, stderr excerpt, retry count, and the resulting rework
  decision. They also surface in Needs Attention. They are never a toast.
- Copy names the problem, the cause when known, and the recovery. "Something went wrong" is
  prohibited, as is any error text that does not tell the user what to do next.
- Raw stack traces sit behind a "Technical details" disclosure, never in the primary message, and
  never visible to a user whose role does not permit it.
- Every error exposes a correlation ID and timestamp, both copyable.
- Redaction of secrets in error payloads is server-side and marked, never trusted to the client.

### 15.3 Empty states

Three kinds, and they are not interchangeable:

| Kind | Content |
|---|---|
| **First run** | What this surface will contain, why it matters, one primary action, one optional documentation link. |
| **Filtered empty** | Names the active filters, states the unfiltered count, offers "Clear filters". Never the first-run message. |
| **Legitimately empty** | Quiet, one line, no action. "No failed gates in this execution." A good outcome is not a problem to solve. |

Anatomy: an optional 20px icon, a one-line sentence-case heading with no period, one or two lines of
explanation at ≤44ch, at most one primary action. Centered in panels; left-aligned in lists and
tables.

Prohibited: illustrations, mascots, large icons, "No data", "Nothing here yet" with no next step, and
any empty state that does not distinguish "you have none" from "your filter matched none".

---

## 16. Accessibility

**WCAG 2.2 Level AA is a hard floor, verified in CI.** Not a later phase.

### 16.1 Contrast

Body and placeholder text ≥4.5:1. Large text (≥18.66px bold / ≥24px) ≥3:1. UI component boundaries,
status glyphs, focus indicators, and chart marks ≥3:1 against their surroundings. Disabled elements
are exempt from the text ratio but must remain identifiable by more than opacity.

Every token pairing in §4 has been measured. New pairings are measured before they ship.

### 16.2 Focus

- `:focus-visible` — 2px solid `blue-600` (light) / `blue-300` (dark), 2px offset, `radius-sm`.
- Focus is **never** removed. `outline: none` without a replacement indicator is a build failure.
- Focus is visible on every interactive element, including table rows, disclosure triangles, chart
  marks, and timeline nodes.
- Overlays trap focus while open and return focus to their trigger on close.
- A skip link to main content is the first tabbable element.

### 16.3 Keyboard

Full operability without a pointer. Logical tab order matching visual order. No keyboard traps.
Tables support arrow-key cell navigation with `Home`/`End`/`PageUp`/`PageDown`. Every pointer-only
affordance has a keyboard equivalent. A command palette (`Ctrl/Cmd+K`) reaches every primary
destination and the Needs Attention queue.

### 16.4 Semantics and assistive technology

- Native HTML first. ARIA only where HTML cannot express the pattern, built to the WAI-ARIA
  Authoring Practices.
- One `h1` per page; heading levels never skip.
- Live regions: `aria-live="polite"` for the execution event feed, **rate-limited to at most one
  announcement per 2 seconds** with a summary ("4 new events") so a fast feed cannot flood a screen
  reader. `aria-live="assertive"` is reserved for gate failures and blocked executions requiring
  action.
- Status changes are announced with their text label, never as a color change.
- Decorative icons are `aria-hidden="true"`; meaningful icons carry accessible names.
- Charts expose an accessible summary and a table view (§17).

### 16.5 Perception and preference

- **Never color alone.** Status = glyph + color + text. Diffs = color + `+`/`−`. Charts = color +
  direct label or pattern.
- `prefers-reduced-motion: reduce` → all non-essential motion becomes instant or opacity-only;
  shimmer stops; the spinner becomes a static indicator with a text label.
- `prefers-contrast: more` → borders step to `border-strong`, tints drop, focus ring goes to 3px.
- Forced-colors mode is supported: no information carried by background color alone.
- 200% zoom without loss of function; 400% reflow to a single column without horizontal scrolling.
- Target size ≥24×24px (WCAG 2.2 SC 2.5.8); ≥44×44px on coarse pointers.
- No content flashes more than three times per second, ever.

### 16.6 Verification

`axe-core` in CI on every route, failing the build on violations. A keyboard-only pass and a screen
reader pass (NVDA + VoiceOver) on the execution, artifact, and gate flows before any release.
Automated checks catch roughly a third of issues; the manual passes are not optional.

---

## 17. Data Visualization

Charts serve comparison and detection. They are never decoration and never a substitute for a table.

### 17.1 Choosing the form

Magnitude across categories → horizontal bar. Change over time → line. Composition over time →
stacked bar. Distribution → histogram or dot plot. A single headline number → a stat readout, not a
chart.

Prohibited: dual-axis charts (two y-scales) — split into two charts or index to a common base; pie
and donut charts beyond three slices; 3D anything; gradient fills under lines; sparklines or progress
rings standing in for content; radial gauges.

### 17.2 Categorical palette

Assigned in fixed order, never cycled. Color follows the entity, never its rank — a filter that
removes a series must not repaint the survivors.

| Slot | Light | Dark |
|---|---|---|
| 1 | `#2563C7` | `#3270D6` |
| 2 | `#C97A0E` | `#B66C02` |
| 3 | `#00968C` | `#00A8A2` |
| 4 | `#B32D63` | `#B43366` |
| 5 | `#6C9A24` | `#75A332` |
| 6 | `#A03C1C` | `#AE411F` |

Validated: lightness band, chroma floor, adjacent-pair CVD separation (deutan/tritan), normal-vision
separation, and contrast against surface — all pass in both themes.

**Series limits, derived from that validation:**

- **≤4 series** — safe under all-pairs comparison. No extra encoding required.
- **5–6 series** — safe adjacent only. **Direct labeling is mandatory**, not optional.
- **>6 series** — never generate a 7th hue. Fold the tail into "Other", facet into small multiples,
  or switch to a table.

### 17.3 Sequential and diverging

Sequential (magnitude, heatmaps, density) — one hue, light→dark, validated monotone:

- Light: `#8DB3EA` `#6596DE` `#3778D7` `#195CB9` `#11458C`
- Dark: `#AFCDF9` `#86B0ED` `#5E93E1` `#3475D3` `#1659B5`

Diverging (variance against a target) — two poles with a neutral midpoint: `#A03C1C` (below) ·
`#E3E6EB` / `#2E3742` (neutral) · `#00968C` (above). **Never red-to-green** — it fails for the most
common form of colorblindness. Never a hue at the midpoint. Never a rainbow scale.

### 17.4 Status in charts

Status hues (§4.3) are reserved. When a chart encodes execution state, it uses the status palette and
nothing else; when a chart encodes identity, it uses the categorical palette and nothing else. The
two never mix in one chart.

### 17.5 Anatomy

- Title states what the chart shows. Axis labels carry units. Bar charts start the value axis at zero.
- Gridlines: horizontal only, 1px `border-subtle`. Axis lines recessive or absent. The data is the
  darkest thing in the frame.
- Marks: 2px lines, ≥8px point markers, 4px rounded data-ends on bars anchored to the baseline, a 2px
  surface-colored gap between adjacent and stacked fills, a 2px surface ring on overlapping marks.
- **Direct labeling over legends** wherever it fits. A legend is present for ≥2 series; a single
  series is named by the title and needs none. Never a number on every point.
- Text in charts wears text tokens (`text-primary`/`text-secondary`), never the series color.
- Tabular figures on every axis label, tick, and value.
- Hover is the default, not an enhancement: crosshair plus tooltip on line and area charts, per-mark
  tooltip on bar, dot, and cell charts. Hit targets exceed the mark.
- Every chart offers a "View data" table toggle. This is the accessibility path and the trust path.
- Dark mode steps are selected and validated separately — never an automatic flip.

---

## 18. Motion

Motion conveys state. Nothing else.

### 18.1 Budget

| Interaction | Duration | Easing |
|---|---|---|
| Hover, focus, color change | 100ms | `linear` |
| Tooltip, dropdown, popover | 150ms | `cubic-bezier(.2,0,0,1)` |
| Panel, drawer, modal | 200ms | `cubic-bezier(.2,0,0,1)` |
| Reversible transitions | 200ms | `cubic-bezier(.4,0,.2,1)` |
| Progress, spinner | continuous | `linear` |

**250ms is the ceiling.** Nothing in this product animates longer.

### 18.2 Rules

- Animate `opacity`, `transform`, `background-color`, `border-color`, and `box-shadow`. Never
  `height`, `width`, `top`, or `left` — use `transform` or an explicit measured collapse.
- **Prohibited:** page-load sequences, staggered list entrances, table rows animating in, numbers
  counting up, parallax, scroll-triggered reveals, decorative loops, pulsing or glowing "processing"
  effects, and any motion on route change beyond a ≤100ms fade.
- Live feeds fade new items in over 120ms. They never slide the list, never move scroll position, and
  never move focus.
- Nothing that represents real-world action state may animate in a way that implies progress it
  cannot measure.

### 18.3 The one authored moment

The product has exactly one expressive motion: **the gate verdict settling.** When a Control Gate
resolves, its stamp scales from 0.98 to 1.0 with an opacity rise over 180ms on an exponential
ease-out — once, on resolution only, never on re-render or navigation.

This is the only place the interface permits itself a gesture, and it is placed on the moment that
matters most. Adding a second such moment dilutes it.

### 18.4 Reduced motion

Under `prefers-reduced-motion: reduce`: the stamp appears without scaling, skeletons stop shimmering,
spinners become static indicators with text labels, and all transitions collapse to ≤100ms opacity or
none. No information is lost — motion never carries meaning alone.

---

## 19. Responsive Behavior

This is a desktop-primary operations product. It is honest about that: mobile is supported for
triage and approval, not for authoring plans or configuring agents.

### 19.1 Breakpoints

`sm 640` · `md 768` · `lg 1024` · `xl 1280` · `2xl 1536`

### 19.2 Structural adaptation

Responsive behavior is **structural, not fluid.** Type sizes are fixed rem at every breakpoint.

| Range | Behavior |
|---|---|
| ≥1536 | Side nav expanded, detail pane open, full column set |
| 1280–1535 | Side nav expanded, detail pane on demand |
| 1024–1279 | Side nav collapses to a 56px icon rail; detail pane becomes an overlay |
| 768–1023 | Nav becomes a drawer; tables reduce to priority columns with a column picker |
| <768 | Tables become stacked record lists of label/value pairs — **never a 12-column horizontal scroll**; the timeline rail moves flush left with timestamps stacked above titles; modals become full-screen sheets; density forces comfortable |

### 19.3 Invariants

- The page body never scrolls horizontally. Wide content scrolls inside its own container.
- The Needs Attention count and the current execution status remain reachable at every size.
- Primary actions never hide behind an overflow menu on the surface where they are primary.
- Test at 1280, 1440, and 1920 for desktop; 768 and 390 for the reduced experience.

---

## 20. Prohibited

Any of these in a shipped surface is a defect, regardless of who asked for it.

**Aesthetic:** purple or multi-hue AI gradients · gradients on UI chrome of any kind · neon or
fully-saturated colors · glowing edges, halos, and colored shadows · glassmorphism and backdrop blur
as decoration · robot, brain, sparkle, wand, or "magic" imagery · AI mascots · emoji anywhere in the
interface · sketch, doodle, or blob illustrations · decorative background patterns and grid overlays
· radii above 8px · shadows on non-floating elements · a border and a shadow on the same element ·
hard offset block shadows · gradient or outlined text.

**Structural:** cards as the default page scaffold · nested cards · nested tables · same-size
icon+heading+text card grids · eyebrow/kicker labels above headings · decorative section numbering ·
a modal for anything that does not require protected focus · infinite scroll on audit surfaces ·
hover-only controls · placeholder text as a label · chat as the primary interface to the platform.

**Integrity — these are correctness failures, not taste:** success styling without linked evidence ·
a progress bar for work with no real denominator · optimistic rendering of a real business action ·
collapsing the six action states into a boolean · a gate verdict without approver, timestamp, and
version · rendering or revealing a stored secret · a toast for an error requiring action · status
carried by color alone · relative time with no absolute value available · a truncated record that
does not say it was truncated.

---

## 21. Governance

- This document is the visual source of truth. Where code and DESIGN.md disagree, DESIGN.md wins
  until it is amended — and amending it is a deliberate act, not a side effect of a feature.
- Every token in §4 is measured, not estimated. New color pairings are validated before they ship;
  new chart palettes are run through the categorical checks in §17.2 before they are committed here.
- Components consume tokens. A raw hex, px radius, or hard-coded duration in a component is a defect.
- New patterns are added to this document in the same change that introduces them. A pattern used
  twice and documented zero times is how design systems die.
- Per-surface strategy that is not durable belongs in a surface brief, not here.

**Open items for a later phase:** the licensed font decision (Inter is the specified default; a
distinctive licensed UI face may replace it without changing any other rule), the tenant theming
boundary, and print/export styling for generated artifacts.
