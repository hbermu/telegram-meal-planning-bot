# Scheduled Notifications

> Two recurring posts to the group chat: next week's plan with its shopping list on Friday, early enough to shop over the weekend, and the day's five meals every weekday morning. Nothing else is ever sent unprompted.

## Source files

- `meal_planning_bot/scheduler.py` — job registration, the weekly and daily callbacks, and the startup catch-up
- `meal_planning_bot/weeks.py` — `current_week_start`, `next_week_start`, and the week a given date belongs to
- `meal_planning_bot/formatting.py` — the weekly and daily message bodies
- `meal_planning_bot/__main__.py` — wires the scheduler to the running application

## Settings used

- `MEALBOT_TIMEZONE` (environment) — IANA zone name for every scheduled time, default `UTC`
- `MEALBOT_GROUP_CHAT_ID` (environment) — the only recipient
- `weekly_post_weekday` (settings table) — weekday of the planning post, 0 for Monday through 6 for Sunday, default `4` (Friday)
- `weekly_post_time` (settings table) — local time of the planning post, default `18:00`
- `daily_post_time` (settings table) — local time of the weekday post, default `08:00`

## Requirements

1. The scheduler shall build every job time as a timezone-aware time in `MEALBOT_TIMEZONE`.
2. The scheduler shall run the weekly job on `weekly_post_weekday` at `weekly_post_time`.
3. When the weekly job runs, the bot shall generate the plan for the **following** Monday's week if none exists, and shall post that plan followed by its shopping list to the group chat.
4. The weekly job shall label its post as next week's plan and shall name the Monday it starts on, so a post read on Friday cannot be mistaken for the current week.
5. The scheduler shall run the daily job Monday to Friday at `daily_post_time`.
6. When the daily job runs, the bot shall post the **current** week's entry for that day: the five slots with each dish's name and effective calories, and the day's calorie total, in one message to the group chat.
7. If no plan exists for the current week when the daily job runs, then the bot shall generate one, post it, and then post the day's meals.
8. When the bot starts, it shall generate and post the current week's plan if that week has none and the current local day is Monday to Friday.
9. When the bot starts, it shall generate and post next week's plan if the current local day is at or past `weekly_post_weekday` and next week has no plan.
10. The bot shall not re-post a plan that already exists when it starts.
11. If a scheduled send fails, then the bot shall log the failure and shall not retry, so a Telegram outage cannot produce a duplicate post later.
12. When `weekly_post_weekday`, `weekly_post_time` or `daily_post_time` is changed through `/set`, the scheduler shall re-register the affected job without a restart.
13. The bot shall never post to any chat other than the configured group from a scheduled job.
14. When generating next week's plan, the bot shall pass the current week's stored entries as history, so the cooldown spans the boundary between the two weeks.

## Tests covering this

- `tests/test_scheduler.py` — job times are timezone-aware and land on the configured local time across a DST boundary; the weekly job is registered for `weekly_post_weekday` only; the daily job is registered for days 0–4 only; the weekly job targets next week's Monday; the daily job targets today's row of the current week; the startup catch-up generates the current week on a Wednesday with no plan and next week on a Saturday, and does nothing when both exist; changing a time or the weekday re-registers only that job
- `tests/test_integration.py` — the weekly and daily jobs post to the group chat and to no other chat

## Non-goals

- Per-meal reminders at meal times. One digest per day.
- Weekend posts of the daily digest.
- Planning more than one week ahead.
- Retrying failed sends or queueing them.
- Direct messages to individual users on a schedule.
