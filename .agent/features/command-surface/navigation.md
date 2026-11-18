# Command Surface — navigation

> Everything the bot can do is reachable with buttons, and every reply is rendered onto a single message per chat, which is edited in place; the message that asked for it is deleted. Consulting the plan and walking the catalogue leave one message behind instead of a screenful, and the content the bot was asked to produce — a shopping list, a scheduled post — stays readable among its own messages instead of being buried under dead menus.

## Source files

- `meal_planning_bot/anchor.py` — the anchor: one message id per chat, the edit-or-send rule, the best-effort deletion
- `meal_planning_bot/telegram_bridge.py` — adapts `telegram.Bot` to the transport `anchor.py` expects, turns every `telegram` error into an `anchor` one, and builds each update's trigger
- `meal_planning_bot/__main__.py` — seeds the one `Anchors` instance into `bot_data` and registers the `menu:` callback handler
- `meal_planning_bot/handlers/keyboards.py` — every shared keyboard and the `menu:` callback vocabulary
- `meal_planning_bot/handlers/menu.py` — the menu tree and its callback routing
- `meal_planning_bot/handlers/plan.py` — the plan, day, shopping and regenerate views both the commands and the menu call; the only handler that posts content instead of rendering a menu

## Settings used

none

## Requirements

1. The bot shall hold at most one anchor per chat, the message every reply to that chat is rendered onto.
2. When a handler replies and the chat holds an anchor, the bot shall edit that message rather than send a new one.
3. When a handler replies and the chat holds no anchor, the bot shall send a new message and shall hold it as the anchor.
4. When an update carries a message the user sent, the bot shall delete that message after answering it.
5. When an update is a button tap and the chat holds no anchor, the bot shall adopt the message the tap arrived on as the anchor.
6. If the chat already holds an anchor, then a button tap shall not displace it.
7. If a deletion fails, then the bot shall carry on as if it had succeeded and shall leave the message on screen.
8. If an edit is refused because it would leave the message exactly as it is, then the bot shall treat that as a success and shall keep the anchor.
9. If an edit fails for any other reason, then the bot shall delete that message, send a new one, and hold the new one as the anchor.
10. The anchor shall be held in memory only, so that restarting the bot forgets it and costs one extra message.
11. When a user sends `/shopping`, the bot shall post the list as messages of its own and shall leave the anchor showing whatever it was showing.
12. The scheduled posts described in `../notifications/overview.md` shall never become the anchor and shall never be edited or deleted.
13. When a user sends `/start`, the bot shall open the main menu.
14. The main menu shall offer the plan, the day, the shopping list, the catalogue, the settings and the help text.
15. Every menu below the main one shall carry a button back to the level above it.
16. The bot shall keep no menu state: every navigation step shall be carried in the tapped button's callback data. The one exception is the custom-dish prompt of `../week-planner/overrides.md`, which waits for text and is held in memory like a wizard.
17. When the regenerate button is tapped, the bot shall ask for confirmation and shall change nothing until the confirming button is tapped.
18. If a tap carries a `menu:` action this version does not know, then the bot shall open the main menu, because an inline keyboard outlives the message it was sent on.
19. Every command the menu covers shall remain available as a typed command.

## Menu tree

```
main          Plan · Hoy · Compra · Catálogo · Ajustes · Ayuda
 plan:<week>  Cambiar una comida · Sortear de nuevo · Compra · the other week · back
 catalog      Platos · Alimentos · Platos archivados · Alimentos archivados · back
 settings     back
 help         back
```

A week is addressed as `now` or `next` in the callback data, mirroring the optional `siguiente` keyword the typed commands take.

## Tests covering this

- `tests/test_anchor.py` — the first reply is sent and the next ones edit it; the triggering message is deleted; a tap adopts its carrier but never displaces a held anchor; a failing deletion is not fatal; an unchanged render sends nothing; an uneditable anchor is replaced and taken off the screen; each chat navigates in its own message; posted content leaves the anchor in place
- `tests/test_integration.py` — four commands in a row produce one sent message, three edits of it and four deletions; a tap after a forgotten anchor adopts the menu on screen; the shopping list posts without moving the anchor
- `tests/test_bridge.py` — an edit that changes nothing maps to the success case, every other Telegram failure maps to one error type, and no `telegram` exception reaches a handler
- `tests/test_handlers.py` — `/start` opens the main menu; every main-menu button answers something; the plan menu walks to next week and back; the regenerate button asks before drawing; the shopping button posts content instead of replacing the menu; an unknown `menu:` action opens the main menu

## Non-goals

- Persisting the anchor. Losing it costs one message, and a tap re-adopts the menu on screen.
- Deleting the bot's own content: a shopping list and a scheduled post stay in the chat.
- A persistent reply keyboard or inline query mode. Navigation is inline buttons on the anchor.
- Editing a message older than Telegram allows. That failure replaces the anchor instead.
