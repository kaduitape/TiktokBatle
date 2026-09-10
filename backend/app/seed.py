import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Battle, Character, ComboTier, Gift

logger = logging.getLogger("seed")

DEFAULT_GIFTS = [
    dict(gift_key="rose", name="Rosa", icon="🌹", action_type="shot", value=-1,
         target_side="A", animation_key="shot", sound_key="shot"),
    dict(gift_key="white_rose", name="Rosa Branca", icon="🤍", action_type="shot", value=-1,
         target_side="B", animation_key="shot", sound_key="shot"),
    dict(gift_key="open_flower", name="Flor Aberta", icon="🌸", action_type="missile", value=-10,
         target_side="A", animation_key="missile", sound_key="missile"),
    dict(gift_key="dino", name="Dino", icon="🦖", action_type="missile", value=-10,
         target_side="B", animation_key="missile", sound_key="missile"),
    dict(gift_key="donut", name="Rosquinha", icon="🍩", action_type="heal", value=30,
         target_side="A", animation_key="heal", sound_key="heal"),
    dict(gift_key="tiktok_ball", name="Bola TikTok Brasil", icon="⚽", action_type="heal", value=30,
         target_side="B", animation_key="heal", sound_key="heal"),
    dict(gift_key="heart_hands", name="Mãos Coração", icon="🫶", action_type="super_heal", value=100,
         target_side="A", animation_key="super_heal", sound_key="super_heal"),
    dict(gift_key="teddy_bear", name="Ursinho", icon="🧸", action_type="super_heal", value=100,
         target_side="B", animation_key="super_heal", sound_key="super_heal"),
]

DEFAULT_COMBO_TIERS = [
    dict(threshold=1, label="TIRO", animation_key="shot", damage_multiplier=1.0),
    dict(threshold=10, label="RAJADA", animation_key="burst", damage_multiplier=1.0),
    dict(threshold=25, label="METRALHADORA", animation_key="minigun", damage_multiplier=1.1),
    dict(threshold=50, label="BAZUCA", animation_key="bazooka", damage_multiplier=1.25),
    dict(threshold=100, label="ATAQUE ESPECIAL", animation_key="special", damage_multiplier=1.5),
]

DEFAULT_CHARACTERS = [
    dict(name="Lado A", team_color="#e74c3c", pos_x=0.25, pos_y=0.5, xp_max=100_000),
    dict(name="Lado B", team_color="#3498db", pos_x=0.75, pos_y=0.5, flip_h=True, xp_max=100_000),
]


async def run_seed(db: AsyncSession) -> None:
    has_gifts = (await db.execute(select(Gift.id).limit(1))).first()
    if not has_gifts:
        for g in DEFAULT_GIFTS:
            db.add(Gift(**g))
        logger.info("seeded %d default gifts", len(DEFAULT_GIFTS))

    has_tiers = (await db.execute(select(ComboTier.id).limit(1))).first()
    if not has_tiers:
        for t in DEFAULT_COMBO_TIERS:
            db.add(ComboTier(**t))
        logger.info("seeded %d default combo tiers", len(DEFAULT_COMBO_TIERS))

    has_characters = (await db.execute(select(Character.id).limit(1))).first()
    if not has_characters:
        chars = [Character(**c) for c in DEFAULT_CHARACTERS]
        for c in chars:
            db.add(c)
        await db.flush()

        has_battle = (await db.execute(select(Battle.id).limit(1))).first()
        if not has_battle:
            db.add(
                Battle(
                    name="Batalha Padrão",
                    side_a_character_id=chars[0].id,
                    side_b_character_id=chars[1].id,
                    max_players=500,
                )
            )
        logger.info("seeded default characters and battle")

    await db.commit()
