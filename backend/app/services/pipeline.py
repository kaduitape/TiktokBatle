import asyncio
import logging
import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.models import (
    Battle,
    BattleEvent,
    BattleSession,
    Character,
    Player,
    TikTokGiftObservation,
)
from app.schemas.schemas import LiveEvent
from app.services.avatar_service import avatar_service
from app.services.battle_manager import battle_manager
from app.services.combo_manager import combo_manager
from app.services.event_normalizer import event_normalizer
from app.services.gift_cache import gift_cache
from app.services.gift_rule_engine import gift_rule_engine
from app.services.settings_service import settings_service
from app.services.tank_war_manager import tank_war_manager
from app.services.team_battle_manager import team_battle_manager
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

            sudden_death_triggered = battle_manager.check_sudden_death(session, battle)

            if event.type == "gift_received":
                if battle.mode == "team_pvp":
                    message = await self._handle_gift_pvp(db, session, battle, event)
                elif battle.mode == "tank_war":
                    message = await self._handle_gift_tank_war(db, session, battle, event)
                else:
                    message = await self._handle_gift(db, session, battle, event)
            elif event.type == "viewer_join":
                message = await self._handle_join(db, session, battle, event)
            elif event.type == "comment":
                message = await self._handle_comment(db, session, battle, event)
            else:
                message = None

            auto_restart = bool(battle.auto_restart)
            battle_id = battle.id
            await db.commit()

        if sudden_death_triggered:
            await connection_manager.broadcast(
                session_id, {"type": "sudden_death", "session_id": session_id}
            )

        if message:
            await connection_manager.broadcast(session_id, message)

        if message and message.get("winner_side") and auto_restart:
            asyncio.create_task(self._auto_restart(session_id, battle_id))

        return message or {}

    async def _auto_restart(self, session_id: str, battle_id: str, countdown: int = 10) -> None:
        """Spec section 40: 'NOVA BATALHA EM: 10 9 8 7 ...' then restart in
        place -- same session_id, so connected arenas don't need to
        reconnect."""
        for remaining in range(countdown, 0, -1):
            await connection_manager.broadcast(
                session_id, {"type": "new_round_countdown", "session_id": session_id, "seconds": remaining}
            )
            await asyncio.sleep(1)

        async with AsyncSessionLocal() as db:
            session = await db.get(BattleSession, session_id)
            battle = await db.get(Battle, battle_id)
            if session is None or battle is None:
                return
            side_a_char = await db.get(Character, battle.side_a_character_id)
            side_b_char = await db.get(Character, battle.side_b_character_id)
            await battle_manager.restart_session(db, session, battle)
            await db.commit()

            message = {
                "type": "battle_restarted",
                "session_id": session.id,
                "xp": {"a": session.side_a_xp, "b": session.side_b_xp},
                "xp_max": {"a": side_a_char.xp_max, "b": side_b_char.xp_max},
            }

        await connection_manager.broadcast(session_id, message)

    async def _handle_gift(
        self, db: AsyncSession, session: BattleSession, battle: Battle, event: LiveEvent
    ) -> dict:
        gift = await self._resolve_gift(db, event)
        if gift is None or not gift.active:
            self._log_unknown_gift(event)
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

        sd_multiplier = battle_manager.sudden_death_multiplier(session, battle)
        xp_manager.apply(
            session, action.target_side, action.total_xp_delta, side_a_char, side_b_char, multiplier=sd_multiplier
        )
        effective_delta = action.total_xp_delta * sd_multiplier

        if effective_delta < 0:
            player.damage_total += abs(effective_delta)
        else:
            player.heal_total += effective_delta
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
                xp_delta=effective_delta,
                target_side=action.target_side,
                payload={"gift_key": gift.gift_key},
            )
        )

        winner = battle_manager.check_victory(session)

        await db.flush()

        return {
            "type": "attack" if effective_delta < 0 else "heal",
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
            "xp_delta": effective_delta,
            "xp": {"a": session.side_a_xp, "b": session.side_b_xp},
            "xp_max": {"a": side_a_char.xp_max, "b": side_b_char.xp_max},
            "winner_side": winner,
            "status": session.status,
            "sudden_death": session.status == "sudden_death",
        }

    async def _handle_join(
        self, db: AsyncSession, session: BattleSession, battle: Battle, event: LiveEvent
    ) -> dict:
        team = (
            await team_battle_manager.assign_balanced_team(db, session.id)
            if battle.mode == "team_pvp"
            else random.choice(["A", "B"])
        )
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

        if battle.mode == "team_pvp" and created:
            config = await settings_service.get(db, "team_battle")
            player.power = team_battle_manager.starting_power(config)
            player.level = team_battle_manager.level_for(player.power, config)

        await db.flush()

        return {
            "type": "player_joined",
            "session_id": session.id,
            "player": self._player_payload(player, created),
        }

    # ------------------------------------------------------------------
    # Team PvP mode (viewers fight each other instead of the characters)
    # ------------------------------------------------------------------

    async def _handle_gift_pvp(
        self, db: AsyncSession, session: BattleSession, battle: Battle, event: LiveEvent
    ) -> dict:
        gift = await self._resolve_gift(db, event)
        if gift is None or not gift.active:
            self._log_unknown_gift(event)
            return {}

        quantity = event.gift.quantity
        combo_count = combo_manager.register(session.id, event.user.id, gift.gift_key, quantity)
        combo_tier = gift_cache.combo_tier_for(combo_count)
        action = gift_rule_engine.resolve(gift, quantity, combo_count, combo_tier)
        config = await settings_service.get(db, "team_battle")

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
        if created:
            player.power = team_battle_manager.starting_power(config)

        growth = team_battle_manager.grow(player, gift.value, quantity, config)
        player.gifts_total += quantity
        player.combo_count = combo_count
        player.last_interaction = datetime.now(timezone.utc)

        # The same gift that grows you also lands as a strike on a random
        # enemy fighter -- healing gifts only grow, they never punch.
        attack = None
        if gift.value < 0:
            alive = await team_battle_manager.alive_players(db, session.id)
            enemies = [p for p in alive if p.team != player.team and p.id != player.id]
            if enemies:
                target = random.choice(enemies)
                result = team_battle_manager.resolve_attack(
                    player, target, config, damage_override=growth.gained
                )
                attack = {
                    "target_user_id": result.target_user_id,
                    "damage": round(result.damage, 1),
                    "target_power": round(result.target_power, 1),
                    "eliminated": result.target_eliminated,
                }

        db.add(
            BattleEvent(
                session_id=session.id,
                player_id=player.id,
                gift_id=gift.id,
                event_type="pvp_gift",
                quantity=quantity,
                combo_count=combo_count,
                xp_delta=growth.gained,
                target_side=action.target_side,
                payload={"gift_key": gift.gift_key, "mode": "team_pvp"},
            )
        )

        await db.flush()

        players = (
            (await db.execute(select(Player).where(Player.session_id == session.id))).scalars().all()
        )
        totals = team_battle_manager.team_totals(players)
        winner = team_battle_manager.winner_from(totals)
        if winner:
            session.status = "finished"
            session.winner_side = winner
            session.finished_at = datetime.now(timezone.utc)

        return {
            "type": "pvp_gift",
            "session_id": session.id,
            "player": self._player_payload(player, created),
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
            "growth": {
                "gained": round(growth.gained, 1),
                "power": round(growth.power, 1),
                "level": growth.level,
                "leveled_up": growth.leveled_up,
            },
            "attack": attack,
            "teams": totals,
            "winner_side": winner,
            "status": session.status,
        }

    # ------------------------------------------------------------------
    # Tank war mode (the characters are the gunners, viewers are the troops)
    # ------------------------------------------------------------------

    async def _handle_comment(
        self, db: AsyncSession, session: BattleSession, battle: Battle, event: LiveEvent
    ) -> dict:
        """Viewers enlist by typing a keyword in chat ("P" or "B" by default).
        Anything else is ordinary chatter and ignored."""
        if battle.mode not in ("tank_war", "team_pvp"):
            return {}

        config = await settings_service.get(db, "tank_war")
        team = tank_war_manager.team_for_comment(event.comment or "", config)
        if team is None:
            return {}

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

        switched = not created and player.team != team
        player.team = team

        queued = False
        if created or player.eliminated or player.power <= 0:
            if battle.mode == "tank_war" and await tank_war_manager.field_is_full(
                db, session.id, config
            ):
                # Arena full: they are enlisted and hold their place in line.
                queued = True
                player.queued = True
                player.power = 0.0
                player.eliminated = False
            else:
                starting = (
                    tank_war_manager.soldier_hp(config)
                    if battle.mode == "tank_war"
                    else team_battle_manager.starting_power(
                        await settings_service.get(db, "team_battle")
                    )
                )
                player.queued = False
                player.power = starting
                player.peak_power = starting
                player.eliminated = False

        player.last_interaction = datetime.now(timezone.utc)
        await db.flush()

        # The arena keeps a live troop count, so every enlistment carries the
        # totals -- otherwise the counter only moved when somebody fired.
        roster = (
            (await db.execute(select(Player).where(Player.session_id == session.id)))
            .scalars()
            .all()
        )

        return {
            "type": "player_enlisted",
            "session_id": session.id,
            "player": self._player_payload(player, created),
            "switched": switched,
            "armies": tank_war_manager.army_totals(roster),
            "queued": queued or bool(player.queued),
            "queue_position": await tank_war_manager.queue_position(db, session.id, player)
            if player.queued
            else 0,
        }

    async def _handle_gift_tank_war(
        self, db: AsyncSession, session: BattleSession, battle: Battle, event: LiveEvent
    ) -> dict:
        gift = await self._resolve_gift(db, event)
        if gift is None or not gift.active:
            self._log_unknown_gift(event)
            return {}

        quantity = event.gift.quantity
        combo_count = combo_manager.register(session.id, event.user.id, gift.gift_key, quantity)
        combo_tier = gift_cache.combo_tier_for(combo_count)
        action = gift_rule_engine.resolve(gift, quantity, combo_count, combo_tier)
        config = await settings_service.get(db, "tank_war")

        # A viewer who already enlisted by comment keeps that side. Somebody who
        # sent a gift without ever typing A or B is dropped into a random team,
        # so the gift still fights for somebody instead of being wasted.
        existing = (
            await db.execute(
                select(Player).where(
                    Player.session_id == session.id, Player.user_id == event.user.id
                )
            )
        ).scalar_one_or_none()
        team = existing.team if existing else tank_war_manager.random_team()

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
        if created or player.eliminated or player.power <= 0:
            # The field is capped, so a newcomer (or somebody coming back from
            # elimination) only walks in if there is room; otherwise they wait.
            if await tank_war_manager.field_is_full(db, session.id, config):
                player.queued = True
                player.power = 0.0
                player.eliminated = False
            else:
                starting = tank_war_manager.soldier_hp(config)
                player.queued = False
                player.power = starting
                player.peak_power = starting
                player.eliminated = False

        # Everybody fires at the enemy boss -- never at each other. The boss's
        # health pool is the same side_a_xp/side_b_xp the classic mode uses, so
        # the clamping and victory checks are shared.
        target_side = tank_war_manager.enemy_side(team)
        damage = tank_war_manager.boss_damage(gift, quantity, config)

        side_a_char = await db.get(Character, battle.side_a_character_id)
        side_b_char = await db.get(Character, battle.side_b_character_id)
        boss_hp = xp_manager.apply(session, target_side, -damage, side_a_char, side_b_char)

        player.gifts_total += quantity
        player.combo_count = combo_count
        player.damage_total += damage
        player.last_interaction = datetime.now(timezone.utc)

        db.add(
            BattleEvent(
                session_id=session.id,
                player_id=player.id,
                gift_id=gift.id,
                event_type="tank_shot",
                quantity=quantity,
                combo_count=combo_count,
                xp_delta=-damage,
                target_side=target_side,
                payload={"gift_key": gift.gift_key, "mode": "tank_war"},
            )
        )

        await db.flush()

        players = (
            (await db.execute(select(Player).where(Player.session_id == session.id))).scalars().all()
        )
        armies = tank_war_manager.army_totals(players)
        winner = battle_manager.check_victory(session)

        return {
            "type": "tank_shot",
            "session_id": session.id,
            "player": self._player_payload(player, created),
            "gift": {
                "key": gift.gift_key,
                "icon": gift.icon,
                "action_type": gift.action_type,
                "animation_key": gift.animation_key,
                "sound_key": gift.sound_key,
                "coins": gift.coins,
                # In this mode every gift does the same thing -- hit the enemy
                # side. All that separates them is how hard, and whether the
                # gift is a special, which is the only visual distinction.
                "is_special": gift.action_type == "special",
            },
            "quantity": quantity,
            "combo": {
                "count": combo_count,
                "tier_label": combo_tier.label if combo_tier else None,
                "tier_animation": combo_tier.animation_key if combo_tier else None,
            },
            "shooter_side": team,
            "target_side": target_side,
            "damage": round(damage, 1),
            "boss_hp": round(boss_hp, 1),
            "xp": {"a": session.side_a_xp, "b": session.side_b_xp},
            "xp_max": {"a": side_a_char.xp_max, "b": side_b_char.xp_max},
            "armies": armies,
            "winner_side": winner,
            "status": session.status,
        }

    async def boss_bomb(self, session_id: str, boss_side: str) -> dict:
        """The boss answers the barrage on its own schedule: a bomb lobbed at
        one active enemy viewer, hard enough to take a full-health soldier out
        (spec of mode 3). Driven by the per-session battle loop."""
        async with AsyncSessionLocal() as db:
            session = await db.get(BattleSession, session_id)
            if session is None or session.status == "finished":
                return {}

            battle = await db.get(Battle, session.battle_id)
            if battle is None or battle.mode != "tank_war":
                return {}

            config = await settings_service.get(db, "tank_war")
            victim_team = tank_war_manager.enemy_side(boss_side)
            target = await tank_war_manager.pick_bomb_target(db, session_id, victim_team, config)
            if target is None:
                return {}

            hit = tank_war_manager.resolve_bomb(target, config)

            # An elimination frees a slot, so the next person in line walks in.
            promoted = None
            if hit.eliminated:
                promoted = await tank_war_manager.promote_from_queue(db, session_id, config)

            db.add(
                BattleEvent(
                    session_id=session_id,
                    player_id=target.id,
                    event_type="boss_bomb",
                    quantity=1,
                    xp_delta=-hit.damage,
                    target_side=victim_team,
                    payload={"mode": "tank_war", "boss_side": boss_side, "eliminated": hit.eliminated},
                )
            )
            await db.commit()

            players = (
                (await db.execute(select(Player).where(Player.session_id == session_id)))
                .scalars()
                .all()
            )
            message = {
                "type": "boss_bomb",
                "session_id": session_id,
                "boss_side": boss_side,
                "victim": {
                    "user_id": hit.user_id,
                    "username": hit.username,
                    "damage": hit.damage,
                    "power": hit.power,
                    "eliminated": hit.eliminated,
                },
                "armies": tank_war_manager.army_totals(players),
                "promoted": self._player_payload(promoted, True) if promoted else None,
            }

        await connection_manager.broadcast(session_id, message)
        return message

    @staticmethod
    def _player_payload(player: Player, created: bool) -> dict:
        return {
            "id": player.id,
            "user_id": player.user_id,
            "username": player.username,
            "nickname": player.nickname,
            "avatar_url": player.avatar_url,
            "team": player.team,
            "created": created,
            "power": round(player.power, 1),
            "level": player.level,
            "kills": player.kills,
            "eliminated": player.eliminated,
            "queued": player.queued,
        }

    async def _resolve_gift(self, db: AsyncSession, event: LiveEvent):
        """Use a provider-specific, immutable ID for real LIVE events.

        Simulator events deliberately keep using the friendly ``gift_key``.
        TikTok events, however, must never be matched by the translated gift
        name: names vary by locale while TikTok's numeric gift ID is stable.
        """
        if event.gift is None:
            return None

        if event.raw.get("provider") != "tiktok":
            return gift_cache.get(event.gift.id)

        await self._record_tiktok_gift_observation(db, event)
        return gift_cache.get_tiktok(event.gift.id)

    async def _record_tiktok_gift_observation(self, db: AsyncSession, event: LiveEvent) -> None:
        """Persist the exact incoming gift so the setup wizard can map it."""
        if event.gift is None:
            return

        gift_id = str(event.gift.id)
        observation = await db.get(TikTokGiftObservation, gift_id)
        now = datetime.now(timezone.utc)
        raw_coins = event.raw.get("coins")
        try:
            coins = int(raw_coins) if raw_coins is not None else None
        except (TypeError, ValueError):
            coins = None

        if observation is None:
            db.add(
                TikTokGiftObservation(
                    tiktok_gift_id=gift_id,
                    name=event.gift.name or gift_id,
                    coins=coins,
                    seen_count=1,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            return

        observation.name = event.gift.name or observation.name
        observation.coins = coins if coins is not None else observation.coins
        observation.seen_count += 1
        observation.last_seen_at = now

    @staticmethod
    def _log_unknown_gift(event: LiveEvent) -> None:
        if event.gift is None:
            return
        if event.raw.get("provider") == "tiktok":
            logger.warning(
                "unmapped TikTok gift id=%s name=%s ignored; map it in Admin -> Ao vivo",
                event.gift.id,
                event.gift.name,
            )
            return
        logger.warning("unknown or inactive gift_key=%s ignored", event.gift.id)


game_pipeline = GamePipeline()
