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
    # Special attacks (spec sections 20-25). animation_key is what the
    # arena routes on -- admins can freely clone any of these with
    # target_side="B" to mirror the attack for the other side.
    dict(gift_key="meteor_strike", name="Meteoro", icon="☄️", action_type="special", value=-50,
         target_side="A", animation_key="meteor", sound_key="meteor", multiplier=1.0),
    dict(gift_key="lightning_strike", name="Raio", icon="⚡", action_type="special", value=-25,
         target_side="A", animation_key="lightning", sound_key="lightning", multiplier=1.0),
    dict(gift_key="airstrike", name="Ataque Aéreo", icon="✈️", action_type="special", value=-30,
         target_side="A", animation_key="airstrike", sound_key="airstrike", multiplier=1.0),
    dict(gift_key="hurricane", name="Furacão", icon="🌪️", action_type="special", value=0,
         target_side="A", animation_key="hurricane", sound_key="hurricane", multiplier=1.0),
    dict(gift_key="shockwave", name="Onda de Choque", icon="💥", action_type="special", value=0,
         target_side="A", animation_key="shockwave", sound_key="shockwave", multiplier=1.0),
    dict(gift_key="giant_avatar", name="Avatar Gigante", icon="🦣", action_type="special", value=0,
         target_side="A", animation_key="giant", sound_key="giant", multiplier=1.0),
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
    # Additive per-item: re-running seed (e.g. after an upgrade that adds new
    # default gifts) never touches gifts/tiers an admin already customized,
    # it only fills in ones that don't exist yet by key/threshold.
    existing_gift_keys = {row[0] for row in (await db.execute(select(Gift.gift_key)))}
    new_gifts = [g for g in DEFAULT_GIFTS if g["gift_key"] not in existing_gift_keys]
    for g in new_gifts:
        db.add(Gift(**g))
    if new_gifts:
        logger.info("seeded %d default gifts", len(new_gifts))

    existing_thresholds = {row[0] for row in (await db.execute(select(ComboTier.threshold)))}
    new_tiers = [t for t in DEFAULT_COMBO_TIERS if t["threshold"] not in existing_thresholds]
    for t in new_tiers:
        db.add(ComboTier(**t))
    if new_tiers:
        logger.info("seeded %d default combo tiers", len(new_tiers))

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
                    mode="character",
                    side_a_character_id=chars[0].id,
                    side_b_character_id=chars[1].id,
                    max_players=500,
                )
            )
            db.add(
                Battle(
                    name="Guerra de Times (PvP)",
                    mode="team_pvp",
                    side_a_character_id=chars[0].id,
                    side_b_character_id=chars[1].id,
                    max_players=500,
                )
            )
        logger.info("seeded default characters and battles")

    await db.commit()
