from dataclasses import dataclass

from app.models.models import ComboTier, Gift


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
    def resolve(gift: Gift, quantity: int, combo_count: int, combo_tier: ComboTier | None) -> ResolvedAction:
        tier_multiplier = combo_tier.damage_multiplier if combo_tier else 1.0
        total_delta = gift.value * quantity * gift.multiplier * tier_multiplier

        # Damage (negative value) hurts target_side, so the attacker is
        # playing for the opposing side. Heals support target_side directly.
        attacker_team = ("B" if gift.target_side == "A" else "A") if gift.value < 0 else gift.target_side

        return ResolvedAction(
            gift=gift,
            quantity=quantity,
            combo_count=combo_count,
            combo_tier=combo_tier,
            target_side=gift.target_side,
            total_xp_delta=total_delta,
            attacker_team=attacker_team,
        )


gift_rule_engine = GiftRuleEngine()
