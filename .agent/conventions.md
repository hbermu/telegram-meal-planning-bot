# Conventions for `.agent/` specs

## EARS notation

All requirements are written using EARS (Easy Approach to Requirements Syntax). EARS constrains free-form text into four patterns; together they express almost everything a feature can require. Use one pattern per requirement; do not combine sentences. Requirements are numbered within their section.

The four patterns:

1. **Ubiquitous** — Always active.
   - Form: `The <subsystem> shall <response>.`
   - Example: `The planner shall fill five slots for each of the five weekdays.`

2. **Event-driven** — Triggered by a specific event.
   - Form: `When <trigger>, the <subsystem> shall <response>.`
   - Example: `When a user sends /regenerate, the bot shall draw a new plan for the current week.`

3. **State-driven** — Active while a condition holds.
   - Form: `While <state>, the <subsystem> shall <response>.`
   - Example: `While a wizard is in progress, the bot shall treat plain text messages as answers to the current step.`

4. **Conditional / optional** — Active when a condition is true.
   - Form: `If <condition>, then the <subsystem> shall <response>.`
   - Example: `If the sender's user ID is not in the allow-list, then the bot shall discard the update without replying.`

Combinations are allowed when the meaning is clearer that way, e.g. `While no plan exists for the current week, when the bot starts, it shall generate one.`

Use the word `shall` for every requirement. Do not use "should", "may", or "will" — those are non-requirements.

## Spec format

Every feature spec uses the structure in `features/_template.md`. Mandatory sections, in order:

1. **Title** (`# <Feature Name>`)
2. **Purpose** — one paragraph, no more
3. **Source files** — file paths under `meal_planning_bot/` with a short note on what each contributes
4. **Settings used** — keys the feature reads or writes, from the environment (`config.py`) or the `settings` table; "none" if it touches neither
5. **Requirements** — numbered EARS list
6. **Commands** — only if the feature adds Telegram commands; otherwise omit the section
7. **Tests covering this** — paths under `tests/` and one-line summaries
8. **Non-goals** — explicit list of things this feature does not do (guards against scope creep)

## Naming

- File names are `kebab-case.md`.
- Use plural for collections (`wizards.md`, not `wizard.md`).
- Directories match the feature slug used in commit scopes.

## Vocabulary

These terms mean exactly one thing across every spec. Do not introduce synonyms.

- **food** — a purchasable ingredient: a name, one unit, one category, one calorie density.
- **dish** — something eaten in one slot: a name, a meal type, a list of foods with quantities, optional preparation steps, and calories computed from those foods unless overridden.
- **reference quantity** — the amount a food's `kcal_ref` refers to: 100 for `g` and `ml`, 1 for `unit`.
- **effective calories** — a dish's `kcal_override` when set, otherwise the value computed from its ingredients. The planner and every message use this.
- **meal type** — one of `breakfast`, `snack`, `lunch`, `dinner`. A property of a dish.
- **slot** — one of `breakfast`, `snack1`, `lunch`, `snack2`, `dinner`. A position in a day. Both snack slots draw from dishes whose meal type is `snack`.
- **day** — an integer 0–4, Monday to Friday.
- **week** — identified by `week_start`, the ISO date of its Monday. The **current** week contains today; the **next** week starts on the following Monday and is the only other week the bot will plan.
- **plan** — the 25 dish assignments for one week.
- **catalogue** — the set of active dishes, grouped by meal type, that the planner may draw from.

## Update rule

Behaviour change → spec change, same commit. This is non-negotiable. Drift between code and spec is treated as a bug.

If a code change merely refactors without altering observable behaviour, no spec change is required — but updating source-file paths in the spec is encouraged when files are renamed or split.

## Deletion rule

When a feature is removed, delete its spec directory in the same commit. Never leave tombstone files, `(removed)` markers, or commented-out spec sections. The history of the repo is the history of the spec; old commits document old behaviour.

## Audit and verification

The `spec-update-check` CI gate fails any change that touches `meal_planning_bot/` without touching `.agent/features/`. It does NOT catch:

- Spec sentences that became false because a refactor updated one spec and missed a cross-reference in another.
- Identifiers (setting keys, command names, slot names, column names, unit values, category values) renamed in code without ripple-updating the spec text.
- Requirements written aspirationally that the implementation never satisfied.
- Duplicate numbering inside a `Requirements` list when a new item was inserted without renumbering downstream entries.

When asked to audit a feature, walk every EARS requirement in `overview.md` and every sub-spec, locate the source files referenced (and any not referenced that the feature actually depends on), and produce a per-requirement met / not-met list with `file:line` evidence. A periodic full audit is the only safety net against silent drift.

## No-external-references rule

Specs reference only:
- Files in this repo (paths relative to repo root).
- Identifiers defined in this repo.
- Setting keys defined in `meal_planning_bot/config.py` or seeded by `meal_planning_bot/migrations.py`.
- Other specs under `.agent/features/`.

Specs MUST NOT contain URLs, links to third-party projects, or references to external standards documents (including this one — EARS is summarised above, not linked). External services may be **named** when the spec describes integrating with them, but never linked.
