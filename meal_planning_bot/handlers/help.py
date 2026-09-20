from meal_planning_bot.access import private_only
from meal_planning_bot.formatting import render_help, render_my_id
from meal_planning_bot.handlers import ContextLike, UpdateLike


async def cmd_start(update: UpdateLike, context: ContextLike) -> None:
    await update.reply_text(render_help())


async def cmd_help(update: UpdateLike, context: ContextLike) -> None:
    await update.reply_text(render_help())


# Unknown commands fall back to the same help text (requirement 10).
cmd_unknown = cmd_help


async def _cmd_myid(update: UpdateLike, context: ContextLike) -> None:
    user = update.effective_user
    assert user is not None  # private chats always carry a sender
    await update.reply_text(render_my_id(user.id))


# The only handler not wrapped by `allowed`: it must work for anyone, so it
# is only ever restricted to a private chat.
cmd_myid = private_only(_cmd_myid)
