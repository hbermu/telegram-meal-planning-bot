from dataclasses import dataclass, field

from meal_planning_bot.anchor import Anchors, NotModified, TransportError, Trigger
from meal_planning_bot.handlers import Keyboard

CHAT = 42
OTHER_CHAT = 77


@dataclass
class Call:
    kind: str
    chat_id: int
    message_id: int
    text: str = ""


@dataclass
class FakeBot:
    calls: list[Call] = field(default_factory=list)
    next_id: int = 100
    not_modified: bool = False
    edit_fails: bool = False
    delete_fails: bool = False

    async def send_message(self, chat_id: int, text: str, keyboard: Keyboard | None) -> int:
        self.next_id += 1
        self.calls.append(Call("send", chat_id, self.next_id, text))
        return self.next_id

    async def edit_message(
        self, chat_id: int, message_id: int, text: str, keyboard: Keyboard | None
    ) -> None:
        self.calls.append(Call("edit", chat_id, message_id, text))
        if self.not_modified:
            raise NotModified("message is not modified")
        if self.edit_fails:
            raise TransportError("message to edit not found")

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.calls.append(Call("delete", chat_id, message_id))
        if self.delete_fails:
            raise TransportError("message can't be deleted for everyone")


def _command(message_id: int, chat_id: int = CHAT) -> Trigger:
    return Trigger(chat_id=chat_id, message_id=message_id, carrier_id=None)


def _tap(carrier_id: int, chat_id: int = CHAT) -> Trigger:
    return Trigger(chat_id=chat_id, message_id=None, carrier_id=carrier_id)


def _kinds(bot: FakeBot) -> list[str]:
    return [call.kind for call in bot.calls]


async def test_the_first_reply_is_sent_and_the_next_ones_edit_it() -> None:
    bot, anchors = FakeBot(), Anchors()

    await anchors.show(bot, _command(1), "primero")
    anchor_id = bot.calls[-1].message_id
    await anchors.show(bot, _command(2), "segundo")
    await anchors.show(bot, _command(3), "tercero")

    assert _kinds(bot) == ["delete", "send", "delete", "edit", "delete", "edit"]
    edits = [call for call in bot.calls if call.kind == "edit"]
    assert [call.message_id for call in edits] == [anchor_id, anchor_id]
    assert [call.text for call in edits] == ["segundo", "tercero"]


async def test_the_message_that_asked_for_a_reply_is_deleted() -> None:
    bot, anchors = FakeBot(), Anchors()

    await anchors.show(bot, _command(7), "hola")

    assert Call("delete", CHAT, 7) in bot.calls


async def test_a_tap_deletes_nothing_and_adopts_the_message_it_came_from() -> None:
    bot, anchors = FakeBot(), Anchors()

    await anchors.show(bot, _tap(55), "menú")

    assert _kinds(bot) == ["edit"]
    assert bot.calls[0].message_id == 55


async def test_an_adopted_anchor_does_not_displace_the_one_already_held() -> None:
    bot, anchors = FakeBot(), Anchors()

    await anchors.show(bot, _command(1), "primero")
    held = bot.calls[-1].message_id
    await anchors.show(bot, _tap(999), "segundo")

    assert [call.message_id for call in bot.calls if call.kind == "edit"] == [held]


async def test_a_failing_deletion_does_not_interrupt_the_reply() -> None:
    bot, anchors = FakeBot(delete_fails=True), Anchors()

    await anchors.show(bot, _command(1), "hola")

    assert _kinds(bot) == ["delete", "send"]


async def test_an_unchanged_render_sends_nothing_new() -> None:
    bot, anchors = FakeBot(), Anchors()
    await anchors.show(bot, _command(1), "igual")
    held = bot.calls[-1].message_id
    bot.not_modified = True

    await anchors.show(bot, _command(2), "igual")

    assert _kinds(bot) == ["delete", "send", "delete", "edit"]
    # Still the anchor: a refused edit that changed nothing is a success.
    bot.not_modified = False
    await anchors.show(bot, _command(3), "distinto")
    assert bot.calls[-1] == Call("edit", CHAT, held, "distinto")


async def test_an_uneditable_anchor_is_replaced_and_taken_off_the_screen() -> None:
    bot, anchors = FakeBot(), Anchors()
    await anchors.show(bot, _command(1), "primero")
    held = bot.calls[-1].message_id
    bot.edit_fails = True

    await anchors.show(bot, _command(2), "segundo")

    assert _kinds(bot) == ["delete", "send", "delete", "edit", "delete", "send"]
    assert bot.calls[-2] == Call("delete", CHAT, held)
    new_anchor = bot.calls[-1].message_id
    assert new_anchor != held

    bot.edit_fails = False
    await anchors.show(bot, _command(3), "tercero")
    assert bot.calls[-1] == Call("edit", CHAT, new_anchor, "tercero")


async def test_each_chat_navigates_in_its_own_message() -> None:
    bot, anchors = FakeBot(), Anchors()

    await anchors.show(bot, _command(1, CHAT), "aquí")
    await anchors.show(bot, _command(1, OTHER_CHAT), "allí")
    await anchors.show(bot, _command(2, CHAT), "aquí otra vez")
    await anchors.show(bot, _command(2, OTHER_CHAT), "allí otra vez")

    edits = [call for call in bot.calls if call.kind == "edit"]
    assert len(edits) == 2
    assert edits[0].chat_id == CHAT
    assert edits[1].chat_id == OTHER_CHAT
    assert edits[0].message_id != edits[1].message_id


async def test_content_is_posted_and_leaves_the_anchor_where_it_was() -> None:
    bot, anchors = FakeBot(), Anchors()
    await anchors.show(bot, _command(1), "menú")
    held = bot.calls[-1].message_id

    await anchors.send(bot, _command(2), "lista de la compra")

    assert _kinds(bot) == ["delete", "send", "delete", "send"]
    await anchors.show(bot, _command(3), "menú otra vez")
    assert bot.calls[-1] == Call("edit", CHAT, held, "menú otra vez")
