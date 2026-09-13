import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import Battle, BattleSession, Character, Player
from app.services.battle_loop import battle_loop
from app.services.team_battle_manager import team_battle_manager
from app.ws.connection_manager import connection_manager

router = APIRouter()
logger = logging.getLogger("ws_routes")


async def _build_state_sync(session_id: str) -> dict | None:
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
                }
                for p in players
            ],
        }


@router.websocket("/ws/arena/{session_id}")
async def arena_socket(websocket: WebSocket, session_id: str):
    await connection_manager.connect(session_id, websocket)
    try:
        state = await _build_state_sync(session_id)
        if state:
            await websocket.send_json(state)

        # PvP fights and boss bombs run on a server tick -- only while
        # somebody is actually watching this session.
        await battle_loop.maybe_start_for_session(session_id)

        while True:
            # Clients don't need to send anything; this just detects disconnects
            # and tolerates any keepalive pings the client chooses to send.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.disconnect(session_id, websocket)
        if connection_manager.connection_count(session_id) == 0:
            await battle_loop.stop(session_id)
