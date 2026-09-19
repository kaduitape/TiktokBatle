from dataclasses import dataclass

from app.models.models import ComboTier, Gift

#: Target options an admin can pick for a gift. The first two name a fixed
#: side; the rest are resolved against whoever sent the gift, which is what
#: makes one rule work for both teams.
TARGET_OPTIONS = ("A", "B", "own_team", "enemy_team", "both", "global")

#: Actions an admin can pick. They are labels for what the gift *does*; the
#: visual is chosen separately by animation_key, so adding one here never
#: requires the arena to learn a new name.
ACTION_OPTIONS = (
    "shot",
    "burst",
    "missile",
    "bomb",
    "meteor",
    "airstrike",
    "lightning",
    "heal",
    "super_heal",
    "shield",
    "special",
    "none",
)

#: Actions that help rather than hurt. Used when a gift's sign alone is not
#: enough to tell which way an effect should point.
SUPPORTIVE_ACTIONS = {"heal", "super_heal", "shield"}


@dataclass
class ResolvedAction:
    gift: Gift
    quantity: int
    combo_count: int
    combo_tier: ComboTier | None
    target_side: str
    total_xp_delta: float
    attacker_team: str


class GiftRuleEngine:
    """The heart of the whole system: turns PRESENTE -> AÇÃO. A gift's
    action_type/value/target/multiplier are 100% data-driven from the Gift
    row, so adding a brand-new gift in the admin panel never requires a
    code change here."""

    @staticmethod
    def resolve(
        gift: Gift,
        quantity: int,
        combo_count: int,
        combo_tier: ComboTier | None,
        sender_team: str | None = None,
    ) -> ResolvedAction:
        tier_multiplier = combo_tier.damage_multiplier if combo_tier else 1.0
        total_delta = gift.value * quantity * gift.multiplier * tier_multiplier

        # "Nenhuma" is a real choice: the admin wants the gift captured and
        # credited to the sender, but with no effect on the battle.
        if gift.action_type == "none":
            total_delta = 0.0

        target_side = GiftRuleEngine.resolve_target_side(gift, sender_team)

        # Damage (negative value) hurts target_side, so the attacker is
        # playing for the opposing side. Heals support target_side directly.
        if sender_team in ("A", "B"):
            # When the sender already belongs to a team, that is their team --
            # inferring it from the target would move people between sides.
            attacker_team = sender_team
        else:
            attacker_team = ("B" if target_side == "A" else "A") if total_delta < 0 else target_side

        return ResolvedAction(
            gift=gift,
            quantity=quantity,
            combo_count=combo_count,
            combo_tier=combo_tier,
            target_side=target_side,
            total_xp_delta=total_delta,
            attacker_team=attacker_team,
        )

    @staticmethod
    def resolve_target_side(gift: Gift, sender_team: str | None) -> str:
        """Turn a symbolic target into the concrete side it means here.

        ``own_team``/``enemy_team`` only mean something once we know who sent
        the gift. Without a sender team -- a viewer who has not picked a side
        yet -- they fall back to the literal sides so the gift still lands
        somewhere sensible instead of being dropped.
        """
        target = gift.target_side or "A"
        if target in ("A", "B"):
            return target

        if target == "own_team":
            if sender_team in ("A", "B"):
                return sender_team
            return "A"
        if target == "enemy_team":
            if sender_team in ("A", "B"):
                return "B" if sender_team == "A" else "A"
            return "B"
        # "both" and "global" have no single side to point at. They are
        # broadcast effects; the side recorded is the enemy's when the gift
        # hurts and the sender's when it helps, so the number still lands on
        # the scoreboard the way the admin would expect.
        if sender_team in ("A", "B"):
            hurts = gift.value < 0 and gift.action_type not in SUPPORTIVE_ACTIONS
            if hurts:
                return "B" if sender_team == "A" else "A"
            return sender_team
        return "A"

    @staticmethod
    def is_broadcast(gift: Gift) -> bool:
        """Whether the effect is meant to be felt by everyone on screen."""
        return (gift.target_side or "") in ("both", "global")


gift_rule_engine = GiftRuleEngine()
