from app.models.models import BattleSession, Character


class XPManager:
    """Applies XP deltas with clamping: XP never exceeds max, never drops
    below zero, and damage/heal always flow through here so the rule is
    enforced in exactly one place."""

    @staticmethod
    def apply(
        session: BattleSession,
        side: str,
        delta: float,
        side_a_char: Character,
        side_b_char: Character,
        multiplier: float = 1.0,
    ) -> float:
        effective_delta = delta * multiplier
        if side == "A":
            new_xp = session.side_a_xp + effective_delta
            new_xp = max(0.0, min(side_a_char.xp_max, new_xp))
            session.side_a_xp = new_xp
        else:
            new_xp = session.side_b_xp + effective_delta
            new_xp = max(0.0, min(side_b_char.xp_max, new_xp))
            session.side_b_xp = new_xp
        return new_xp


xp_manager = XPManager()
