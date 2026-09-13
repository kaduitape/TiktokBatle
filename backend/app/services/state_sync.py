"""Building the full picture of a session for a freshly-arrived client.

An arena gets this on connect, and again whenever something that is not a
score change happens -- a restart after the admin swapped a character's
artwork, say. Sending it is what lets an OBS browser source pick up a change
without being reopened.
"""
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import Battle, BattleSession, Character, Player
from app.services.team_battle_manager import team_battle_manager


async def build_state_sync(session_id: str) -> dict | None:
    async with AsyncSessionLocal() as db:
        session = await db.get(BattleSession, session_id)
        if not session:
            return None
        battle = await db.get(Battle, session.battle_id)
        side_a = await db.get(Character, battle.side_a_character_id)
        side_b = await db.get(Character, battle.side_b_character_id)
        players = (
            (await db.execute(select(Player).where(Player.session_id == session_id)))
            .scalars()
            .all()
        )

        def char_payload(c: Character) -> dict:
            return {
                "id": c.id,
                "name": c.name,
                "image_url": c.image_url,
                "background_url": c.background_url,
                "team_color": c.team_color,
                "scale": c.scale,
                "pos_x": c.pos_x,
                "pos_y": c.pos_y,
                "flip_h": c.flip_h,
                "shadow": c.shadow,
                "outline": c.outline,
                "glow": c.glow,
                "sprite_columns": c.sprite_columns,
                "sprite_rows": c.sprite_rows,
                "sprite_frame_count": c.sprite_frame_count,
                "sprite_fps": c.sprite_fps,
                "hit_image_url": c.hit_image_url,
                "fire_image_url": c.fire_image_url,
                "xp_max": c.xp_max,
            }

        return {
            "type": "state_sync",
            "session_id": session.id,
            "status": session.status,
            "winner_side": session.winner_side,
            "battle": {
                "id": battle.id,
                "name": battle.name,
                "mode": battle.mode,
                "background_url": battle.background_url,
                "max_players": battle.max_players,
            },
            "side_a": char_payload(side_a),
            "side_b": char_payload(side_b),
            "xp": {"a": session.side_a_xp, "b": session.side_b_xp},
            "teams": team_battle_manager.team_totals(players),
            "players": [
                {
                    "id": p.id,
                    "user_id": p.user_id,
                    "username": p.username,
                    "nickname": p.nickname,
                    "avatar_url": p.avatar_url,
                    "team": p.team,
                    "power": round(p.power, 1),
                    "level": p.level,
                    "kills": p.kills,
                    "eliminated": p.eliminated,
                    "queued": p.queued,
                }
                for p in players
            ],
        }
