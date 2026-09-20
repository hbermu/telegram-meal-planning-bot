# AGENTS.md

Onboarding file for AI coding agents working on this repo. Read this before touching anything else. Detailed behavioural specs for each feature live under `.agent/features/`.

## Project overview

A Telegram bot that runs a household's weekly meal plan. It keeps a catalogue of foods and dishes, draws a Monday-to-Friday menu at random under nutrition and variety constraints, publishes the plan and the aggregated shopping list to a group chat every Monday, and posts the day's meals every weekday morning. Dishes and foods are added through step-by-step wizards in a private chat. Interaction is restricted to an allow-list of Telegram user IDs. The bot is a single long-running process with a SQLite database, packaged as a container image.

## Hard rules

### Environment

- Python 3.13. One runtime dependency: `python-telegram-bot`. Everything else comes from the standard library.
- Never install packages into the system interpreter. Use `.venv/` (`python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`).
- The database is a local file. Never point `MEALBOT_DB_PATH` at a network filesystem — SQLite's locking is unreliable over NFS and SMB, and a file written that way opens fine while being subtly corrupt.

### Code style

- Type hints on every function signature. `mypy --strict` must pass.
- No trailing or "what this does" comments. The code names things; comments are for non-obvious **why** only.
- No docstrings on self-explanatory functions. Module-level docstrings only where the module's role is not obvious from its name.
- No error handling for cases that cannot happen. Trust internal callers; validate only at system boundaries (Telegram input, environment variables, the database file).
- No backwards-compat shims, no deprecated re-exports, no `# removed` comments. Dead code is deleted.
- No new helpers that are used once.
- `planner.py`, `shopping.py`, `nutrition.py` and `weeks.py` are pure: they take plain dataclasses and return plain dataclasses. They must not import `sqlite3`, `telegram`, or `datetime.now`. Every source of nondeterminism is injected (a `random.Random` instance, a date).
- Every user-visible string lives in `formatting.py`. Handlers build data, `formatting.py` turns it into text. Handlers must not contain message templates.
- All user-facing text is Spanish. Identifiers, comments, commit messages, and documentation are English.

### Self-contained and anonymous

- This repository builds and publishes a container image. It does not deploy anything, and it does not describe where it is deployed.
- No orchestrator manifest, deploy workflow, host name, node name, storage class, secret name, network address, file path outside this repository, or personal detail belongs here — not in code, not in CI, not in `.agent/`, not in `docs/`. The `README.md` may show a plain `docker run` as usage, and nothing beyond that.
- A reader who clones this repository should learn how the bot works and nothing about whoever runs it.
- Deployment is out of scope. If a task asks you to change how the bot is deployed, that edit does not belong in this repository; say so rather than adding a manifest, a hostname or a path here.

### Git

- Never use `--no-verify` or any flag that bypasses hooks or signing.
- Never force-push. Never move existing tags. To replace a release, bump to the next version.
- Commit subjects follow Conventional Commits: `<type>(<scope>): <subject>`, where `<scope>` is a feature slug (`planner`, `catalog`, `shopping`, `notifications`, `access`, `storage`, `commands`) or `deps`, `ci`, `docs`, `repo`.

### AI documentation

- Anything in `AGENTS.md`, `CLAUDE.md`, or `.agent/` is self-contained — no external URLs, no third-party service links, no references to external standards documents. `README.md` is the only file that may carry external links.
- Every code change that affects observable behaviour MUST update the corresponding `.agent/features/<feature>/<file>.md` in the same commit, using the template at `.agent/features/_template.md`. Spec drift is a bug.
- When a feature is removed, delete its spec directory in the same commit. No tombstone files.
- Documentation precedence for AI agents is: `.agent/features/**` (behaviour contract) → `AGENTS.md` (repo rules + workflow) → `CLAUDE.md` (agent-specific deltas).
- Keep these three sources aligned when one of them changes. If a rule changes in one file and applies globally, mirror it in the others in the same commit.

## Build, test, typecheck

| Command | What it runs |
|---------|--------------|
| `.venv/bin/pytest` | the whole test suite |
| `.venv/bin/pytest tests/test_planner.py -q` | planner only — the fast loop while working on constraints |
| `.venv/bin/mypy --strict meal_planning_bot` | type check |
| `.venv/bin/ruff check .` | lint |
| `.venv/bin/ruff format .` | format |
| `docker build -t meal_planning_bot:dev .` | production image |

Run `.venv/bin/ruff check . && .venv/bin/mypy --strict meal_planning_bot && .venv/bin/pytest` before every commit. CI runs the same three plus the image build.

Tests never talk to Telegram and never open a network socket. Repository tests run against `sqlite3.connect(":memory:")`. Planner tests build synthetic catalogues in code and pass a seeded `random.Random`.

## Where to find what

- **Behavioural specs (canonical)**: `.agent/features/<feature>/`. Each feature has `overview.md` plus sub-spec files for finer sub-functionalities. Specs use EARS notation (defined in `.agent/conventions.md`) and list source files, settings, commands, tests, and non-goals.
- **AI conventions**: `.agent/conventions.md`. Defines EARS, the spec template, naming, and the update/deletion rules.
- **Design decisions and rationale**: `docs/superpowers/specs/`. Why the design is what it is. Not a behaviour contract — when it disagrees with `.agent/features/**`, the spec wins.
- **User-facing docs**: `README.md`.

### Source tree

```
meal_planning_bot/
  __main__.py        # Entry point: config, DB open, handler registration, job scheduling, polling
  config.py          # Environment variables → frozen Config dataclass; fails fast on missing values
  db.py              # Connection factory, PRAGMAs, schema version dispatch
  migrations.py      # Ordered migration functions keyed by PRAGMA user_version
  models.py          # Food, Dish, DishIngredient, Plan, PlanEntry, Settings dataclasses
  repo.py            # Every SQL statement in the project. Nothing else executes SQL.
  nutrition.py       # Pure: computed and effective calories, plus the seed lookup
  weeks.py           # Pure: current and next week_start, the `siguiente` keyword
  data/kcal_seed.json  # Curated ingredient calorie table, generated offline, read-only
  planner.py         # Pure constraint solver: catalogue + history + settings → a week
  shopping.py        # Pure aggregation: a week → a categorised shopping list
  formatting.py      # Every user-visible Spanish string
  access.py          # Allow-list decorator and private-chat guard
  scheduler.py       # Weekly and daily job registration, catch-up on startup
  telegram_bridge.py # Adapts real telegram Updates to the handlers' Protocols
  handlers/
    plan.py          # /plan /today /shopping /regenerate /swap
    catalog.py       # /dishes /dish /foods
    wizards.py       # /newdish /editdish /deletedish /newfood /editfood /deletefood /cancel
    settings.py      # /settings /set
    help.py          # /start /help /myid
tests/
```

## Known pitfalls

- `python-telegram-bot` job times are timezone-aware. Build them with `zoneinfo.ZoneInfo(config.timezone)`, never with naive `datetime.time`, or the Monday post drifts by an hour twice a year.
- A conversation wizard left half-finished blocks nothing, but its state lives in memory and is lost on restart. Wizards must write nothing to the database until the final confirmation step.
- Deleting a dish that appears in a past plan would orphan history. Deletion is always `active = 0`, never `DELETE`, and `/restore` sets it back.
- A dish's calories are resolved, never stored on a plan. Changing a food's `kcal_ref` retroactively changes what an old plan reports. That is deliberate; do not add a snapshot column to "fix" it.
- SQLite integer division and Python integer division differ for negatives. Do arithmetic in Python, not in SQL.

## The update rule (repeated for emphasis)

Behaviour change → spec change, same commit. Spec drift is a bug, not a chore.
