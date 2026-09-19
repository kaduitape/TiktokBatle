"""Stops a streak from being counted more than once.

TikTok reports "Rose x50" in one of two ways depending on the room and the
client version:

* one final event carrying ``repeat_count = 50``; or
* a series of events carrying 1, 2, 3 ... 50 as the streak builds.

Acting on every event of the second form charges 1+2+3+...+50 = 1275 damage
for a 50-damage gift. Dropping intermediate events instead loses the whole
streak whenever the final one never arrives -- which happens when the viewer
leaves, or the socket drops mid-combo.

So neither: this guard remembers the highest count already applied for a
streak and lets through only the part that is new. A streak seen as
1,2,3,...,50 applies 1 then 1 then 1..., totalling exactly 50, and the same
streak seen as a single 50 applies 50 once. Either way the game charges 50.

A repeated event with no streak information at all (no combo id, no repeat
count) is left alone: two separate roses a second apart are two roses, and
guessing otherwise would silently swallow real gifts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.services.gift_normalizer import CapturedGift

# How long a streak stays open. TikTok closes a combo after a few seconds of
# silence; anything later is a new streak that starts counting from zero.
STREAK_WINDOW_SECONDS = 15.0


@dataclass
class _Streak:
    applied: int
    last_ts: float
    closed: bool = False


class GiftStreakGuard:
    def __init__(self) -> None:
        self._streaks: dict[tuple, _Streak] = {}

    def applicable_quantity(self, session_id: str, captured: CapturedGift) -> int:
        """How much of this event the game should actually act on.

        Returns 0 when the event carries nothing new -- a duplicate delivery,
        or an intermediate streak update already covered by an earlier one.
        """
        if captured.sender is None:
            return captured.quantity

        # Without a cumulative count there is nothing to deduplicate against:
        # the provider is reporting discrete gifts, so take it at its word.
        if captured.repeat_count is None and captured.combo_id is None:
            return captured.quantity

        key = self._key(session_id, captured)
        now = time.time()
        streak = self._streaks.get(key)
        if streak is not None and (
            streak.closed or (now - streak.last_ts) > STREAK_WINDOW_SECONDS
        ):
            streak = None

        # The running total the provider claims for this streak so far. When it
        # only sent a combo id, fall back to accumulating the per-event amount.
        already = streak.applied if streak else 0
        if captured.repeat_count is not None:
            cumulative = max(captured.repeat_count, already)
            new_amount = cumulative - already
        else:
            cumulative = already + captured.quantity
            new_amount = captured.quantity

        self._streaks[key] = _Streak(
            applied=cumulative,
            last_ts=now,
            # repeat_end marks the last event of the combo. Closing it means the
            # next gift of the same kind starts a fresh streak immediately,
            # instead of being mistaken for more of this one.
            closed=bool(captured.repeat_end),
        )
        self._prune(now)
        return max(0, new_amount)

    def reset(self, session_id: str) -> None:
        self._streaks = {
            key: streak for key, streak in self._streaks.items() if key[0] != session_id
        }

    @staticmethod
    def _key(session_id: str, captured: CapturedGift) -> tuple:
        sender_id = captured.sender.user_id if captured.sender else ""
        # A combo id identifies the streak exactly. Without one, a streak is
        # "this viewer sending this gift right now", which is the best the
        # provider lets us do.
        return (
            session_id,
            captured.platform,
            sender_id,
            captured.combo_id or captured.platform_gift_id,
        )

    def _prune(self, now: float) -> None:
        if len(self._streaks) < 512:
            return
        self._streaks = {
            key: streak
            for key, streak in self._streaks.items()
            if (now - streak.last_ts) <= STREAK_WINDOW_SECONDS
        }


gift_streak_guard = GiftStreakGuard()
