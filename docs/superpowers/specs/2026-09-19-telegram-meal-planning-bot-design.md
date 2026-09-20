# Meal-planning Telegram bot — design decisions

Date: 2026-09-19

This document records **why** the system is shaped the way it is. It is not a behaviour contract — `.agent/features/**` is. When the two disagree, the spec wins and this file is stale.

## Problem

Plan what the household eats Monday to Friday without thinking about it every week, get one shopping list that covers the whole plan, and keep the recipes somewhere reachable from a phone.

## Decisions

### Shared plan, not per-user

One plan per week for the whole household. Per-user diets would put a profile column on every table and produce several shopping lists, for a household that eats together. Rejected as unused complexity.

### Calories are typed per dish, not computed from foods

A food catalogue with kcal per 100 g is more precise and much more work to populate, and the precision is false anyway — portions are eyeballed. A hand-entered figure per dish is good enough for a ±10 % daily target. Foods still exist, but only so the shopping list can add quantities and group them by aisle.

Consequence: changing a dish's ingredients does not change its calories. That is accepted.

### Dish and recipe are the same entity

The thing that gets planned and the thing that gets read as a recipe are one row with an optional free-text preparation field. Two entities would have needed a join, a second creation flow, and a rule for what happens to a recipe with no dish.

### Target with tolerance, not a hard cap

A hard ceiling on daily calories interacts badly with a small catalogue and hand-estimated figures: many weeks would have no solution, or would be solved by five low-calorie days. A window around a target keeps the search feasible and the days even.

### Cooldown in days, per meal type

The requirement was "try not to repeat week to week, but for breakfast, snacks and dinner not repeating two days running is enough". Two different mechanisms would have been two things to debug. Instead there is one mechanism — a minimum gap in days before a dish may return — configured per meal type: 14 days for lunch, 1 day for the rest. "Not two days running" is the same rule with the gap set to 1.

### A backtracking solver, not a scorer

Twenty-five slots with hard constraints is a constraint-satisfaction problem, and a randomised depth-first search with pruning solves it in milliseconds at this catalogue size. A weighted scorer would always return something, which sounds better until it quietly returns a plan that breaks a rule the user believed was enforced. Failing loudly, then relaxing in a documented order and saying so, is more honest.

The node cap exists because a catalogue can be unsatisfiable in ways that are expensive to prove.

### The planner is pure

`planner.py` takes dataclasses and a seeded `random.Random` and returns dataclasses. No database, no clock, no Telegram. This is the only part of the system with real logic, and purity is what makes it testable: every constraint and every relaxation step gets a unit test against a synthetic catalogue, with no fixtures and no mocking.

The same applies to `shopping.py`.

### SQLite on local storage

The dataset is a few hundred rows and one writer. Postgres would be a service to run and back up for no gain. Network filesystems are ruled out: SQLite's locking is unreliable over NFS and SMB, and a database written that way opens fine while being subtly corrupt. That constraint is written into `AGENTS.md` and the README rather than left as folklore, because it is the kind of thing that gets rediscovered the expensive way.

### Soft deletion

A dish that appears in a past plan cannot be deleted without orphaning history, and history is what the cooldown reads. Deactivation is the only removal.

### `python-telegram-bot`, not the raw API

A standard-library-only bot is very reasonable when the job is menus and file transfers with no state. This bot's centre of gravity is different — six multi-step wizards and two scheduled jobs. `ConversationHandler` and `JobQueue` are exactly those two problems solved, and reimplementing them would be more code to maintain than the dependency is.

### Settings split between environment and database

Secrets and identities (token, allow-list, group chat, database path, timezone) are environment variables: they are injected by whatever runs the container, and changing them is a deploy. Tunables (calorie target, tolerance, repetition limits, cooldowns, post times) are database rows changed with `/set`, because wanting to nudge the calorie target should not require a commit.

### Allow-list in the environment, not the database

An in-band `/allow` command is a second authorisation path to get wrong. The list changes rarely; a redeploy is an acceptable cost for having exactly one way in.

### Spanish interface, English code

The bot is read by the household. The repository will be public, so the code, the specs, and the README are English. Every Spanish string is confined to `formatting.py` so the split does not leak.

### Public container image from day one

The image carries no secrets, so publishing the registry package publicly means whatever runs it needs no pull credentials, and nothing has to change when the repository itself goes public.

## Rejected alternatives

- **Go**: a smaller image, but the solver and the wizards are both faster to write and to change in Python.
- **One-line commands** (`/dish name | lunch | 520 | chicken 200g`): fast to type on a keyboard, painful on a phone, and impossible to correct.
- **A YAML catalogue in the repository**: appealing if you like versioning everything, but it contradicts the requirement to add dishes from the bot, and it would put the household's diet in a public repository.
- **Per-meal reminders**: five messages a day in a group chat is noise. One digest.
- **Storing shopping lists**: they are a pure function of the plan. Storing them creates a second thing that can be stale.

## Open questions

None. Every question raised during design was answered before this document was written.
