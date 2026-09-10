import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.models import Battle, BattleEvent, BattleSession, Character, Player
from app.schemas.schemas import LiveEvent
from app.services.avatar_service import avatar_service
from app.services.battle_manager import battle_manager
from app.services.combo_manager import combo_manager
from app.services.event_normalizer import event_normalizer
from app.services.gift_cache import gift_cache
from app.services.gift_rule_engine import gift_rule_engine
from app.services.xp_manager import xp_manager
from app.ws.connection_manager import connection_manager

logger = logging.getLogger("pipeline")


class GamePipeline:
    """The core end-to-end flow from spec section 56:

    ESPECTADOR -> PRESENTE -> IDENTIFICAR USUARIO -> OBTER AVATAR ->
    LOCALIZAR/CRIAR BOLINHA -> BOLINHA EXECUTA ACAO -> PROJETIL ATINGE
    PERSONAGEM -> XP ALTERADO -> EFEITO VISUAL -> RANKING ATUALIZADO.

    A single entry point (handle_event) is used by the simulator, by the
    real-time queue worker, and eventually by the TikTok provider, so there
    is exactly one code path producing animations -- never a separate one
    for "simulated" vs "real" events (spec section 45).
    """

    async def handle_event(self, session_id: str, event: LiveEvent) -> dict:
        event = event_normalizer.normalize(event)

        async with AsyncSessionLocal() as db:
            session = await db.get(BattleSession, session_id)
            if session is None:
                raise ValueError(f"unknown battle session {session_id}")

            battle = await db.get(Battle, session.battle_id)
            await gift_cache.ensure_loaded(db)

            if event.type == "gift_received":
                message = await self._handle_gift(db, session, battle, event)
            elif event.type == "viewer_join":
                message = await self._handle_join(db, session, battle, event)
            else:
                message = None

            await db.commit()

        if message:
            await connection_manager.broadcast(session_id, message)
        return message or {}

    async def _handle_gift(
        self, db: AsyncSession, session: BattleSession, battle: Battle, event: LiveEvent
    ) -> dict:
        gift = gift_cache.get(event.gift.id)
        if gift is None or not gift.active:
            logger.warning("unknown or inactive gift_key=%s ignored", event.gift.id)
            return {}

        quantity = event.gift.quantity
        combo_count = combo_manager.register(session.id, event.user.id, gift.gift_key, quantity)
        combo_tier = gift_cache.combo_tier_for(combo_count)

        action = gift_rule_engine.resolve(gift, quantity, combo_count, combo_tier)

        side_a_char = await db.get(Character, battle.side_a_character_id)
        side_b_char = await db.get(Character, battle.side_b_character_id)

        player, created = await avatar_service.get_or_create_player(
            db,
            session.id,
            battle,
            user_id=event.user.id,
            username=event.user.username,
            nickname=event.user.nickname,
            avatar_url=event.user.avatar,
            team=action.attacker_team,
        )

        new_xp = xp_manager.apply(session, action.target_side, action.total_xp_delta, side_a_char, side_b_char)

        if action.total_xp_delta < 0:
            player.damage_total += abs(action.total_xp_delta)
        else:
            player.heal_total += action.total_xp_delta
        player.gifts_total += quantity
        player.combo_count = combo_count
        player.last_interaction = datetime.now(timezone.utc)

        db.add(
            BattleEvent(
                session_id=session.id,
                player_id=player.id,
                gift_id=gift.id,
                event_type="gift",
                quantity=quantity,
                combo_count=combo_count,
                xp_delta=action.total_xp_delta,
                target_side=action.target_side,
                payload={"gift_key": gift.gift_key},
            )
        )

        winner = battle_manager.check_victory(session)

        await db.flush()

        return {
            "type": "attack" if action.total_xp_delta < 0 else "heal",
            "session_id": session.id,
            "player": {
                "id": player.id,
                "user_id": player.user_id,
                "username": player.username,
                "nickname": player.nickname,
                "avatar_url": player.avatar_url,
                "team": player.team,
                "created": created,
            },
            "gift": {
                "key": gift.gift_key,
                "icon": gift.icon,
                "action_type": gift.action_type,
                "animation_key": gift.animation_key,
                "sound_key": gift.sound_key,
            },
            "quantity": quantity,
            "combo": {
                "count": combo_count,
                "tier_label": combo_tier.label if combo_tier else None,
                "tier_animation": combo_tier.animation_key if combo_tier else None,
            },
            "target_side": action.target_side,
            "xp_delta": action.total_xp_delta,
            "xp": {"a": session.side_a_xp, "b": session.side_b_xp},
            "xp_max": {"a": side_a_char.xp_max, "b": side_b_char.xp_max},
            "winner_side": winner,
            "status": session.status,
        }

    async def _handle_join(
        self, db: AsyncSession, session: BattleSession, battle: Battle, event: LiveEvent
    ) -> dict:
        import random

        team = random.choice(["A", "B"])
        player, created = await avatar_service.get_or_create_player(
            db,
            session.id,
            battle,
            user_id=event.user.id,
            username=event.user.username,
            nickname=event.user.nickname,
            avatar_url=event.user.avatar,
            team=team,
        )
        await db.flush()

        return {
            "type": "player_joined",
            "session_id": session.id,
            "player": {
                "id": player.id,
                "user_id": player.user_id,
                "username": player.username,
                "nickname": player.nickname,
                "avatar_url": player.avatar_url,
                "team": player.team,
                "created": created,
            },
        }


game_pipeline = GamePipeline()
