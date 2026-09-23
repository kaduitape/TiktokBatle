import time
from dataclasses import dataclass

COMBO_WINDOW_SECONDS = 6.0


@dataclass
class ComboState:
    gift_key: str
    count: int
    last_ts: float


class ComboManager:
    """Detects consecutive same-gift streaks per (session, user) so a burst
    of e.g. 100 roses becomes one aggregated combo event instead of 100
    independent animations (spec sections 17 and 26)."""

    def __init__(self) -> None:
        self._state: dict[tuple[str, str], ComboState] = {}

    def register(self, session_id: str, user_id: str, gift_key: str, quantity: int) -> int:
        key = (session_id, user_id)
        now = time.time()
        state = self._state.get(key)

        if state and state.gift_key == gift_key and (now - state.last_ts) <= COMBO_WINDOW_SECONDS:
            state.count += quantity
            state.last_ts = now
        else:
            state = ComboState(gift_key=gift_key, count=quantity, last_ts=now)
            self._state[key] = state

        return state.count

    def reset(self, session_id: str, user_id: str) -> None:
        self._state.pop((session_id, user_id), None)

    def reset_session(self, session_id: str) -> None:
        """Forget every streak in a session.

        Used when the arena is emptied: a name that comes back afterwards
        would otherwise inherit the combo of the person just removed.
        """
        self._state = {
            key: state for key, state in self._state.items() if key[0] != session_id
        }


combo_manager = ComboManager()
