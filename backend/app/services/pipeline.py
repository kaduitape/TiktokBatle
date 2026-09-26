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
)
from app.schemas.schemas import LiveEvent
from app.services.avatar_service import avatar_service
from app.services.battle_manager import battle_manager
from app.services.combo_manager import combo_manager
from app.services.event_normalizer import event_normalizer
from app.services.gift_cache import gift_cache
from app.services.gift_capture_service import gift_capture_service
from app.services.gift_rule_engine import gift_rule_engine
from app.services.settings_service import settings_service
from app.services.tank_war_manager import tank_war_manager
from app.services.team_battle_manager import team_battle_manager
from app.services.xp_manager import xp_manager
from app.ws.admin_channel import admin_channel
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
                # Capture comes first and runs for EVERY gift, configured or
                # not: the catalogue is how a gift stops needing a code change.
                # It also returns how much of a streak is genuinely new, which
                # is the quantity the rest of the pipeline must act on.
                capture = await gift_capture_service.capture(db, session_id, event)
                if capture is not None:
                    if capture.quantity <= 0:
                        # Already charged as part of this streak. Recording it
                        # twice is what turns "Rose x50" into 1275 damage.
                        await db.commit()
                        return {}
                    event.gift.quantity = capture.quantity
                    if capture.learning:
                        # Learning mode: discover the gift, touch nothing else.
                        logger.info(
                            "modo aprendizagem: %s x%s capturado sem efeito no jogo",
                            capture.captured.platform_gift_id,
                            capture.quantity,
                        )
                        await db.commit()
                        return {}

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
            elif event.type == "like":
                message = await self._handle_like(db, session, battle, event)
            elif event.type == "follow":
                message = await self._handle_follow(db, session, battle, event)
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
        if gift is not None and not await gift_cache.allows(db, battle.id, gift):
            logger.info("gift_key=%s não faz parte desta batalha, ignorado", gift.gift_key)
            return {}
        if gift is None or not gift.active:
            self._log_unknown_gift(event)
            return {}

        quantity = event.gift.quantity
        combo_count = combo_manager.register(session.id, event.user.id, gift.gift_key, quantity)
        combo_tier = gift_cache.combo_tier_for(combo_count)

        # "Próprio time"/"Time adversário" only mean something once we know
        # which side the sender is on, so look them up before resolving. A
        # first-time viewer has no team yet and the rule falls back to a fixed
        # side, which is what the A/B options do anyway.
        sender_team = await self._existing_team(db, session.id, event.user.id)
        action = gift_rule_engine.resolve(gift, quantity, combo_count, combo_tier, sender_team)

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
        simulated_team = (
            event.raw.get("simulated_team")
            if event.raw.get("simulated") and event.raw.get("simulated_team") in ("A", "B")
            else None
        )
        team = simulated_team or (
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

    async def _handle_like(
        self, db: AsyncSession, session: BattleSession, battle: Battle, event: LiveEvent
    ) -> dict:
        """A TikTok heart restores the sender's own side.

        In character and tank modes the heart flies to that side's boss. Team
        PvP has no boss, so the sender's fighter receives the life directly.
        A like never invents a team: the viewer must already be participating.
        """
        player = await self._active_social_player(db, session, battle, event)
        if player is None:
            return {}

        config = await settings_service.get(db, "social_actions")
        try:
            reported = int(event.raw.get("like_count", 1))
        except (TypeError, ValueError):
            reported = 1
        count = max(1, min(reported, int(config.get("max_likes_per_event", 100))))
        requested = count * float(config.get("heal_per_like", 100))

        side_a_char = await db.get(Character, battle.side_a_character_id)
        side_b_char = await db.get(Character, battle.side_b_character_id)
        teams = None

        if battle.mode == "team_pvp":
            before = player.power
            player.power += requested
            player.peak_power = max(player.peak_power, player.power)
            team_config = await settings_service.get(db, "team_battle")
            player.level = team_battle_manager.level_for(player.power, team_config)
            applied = player.power - before
            roster = (
                (await db.execute(select(Player).where(Player.session_id == session.id)))
                .scalars()
                .all()
            )
            teams = team_battle_manager.team_totals(roster)
        else:
            before = session.side_a_xp if player.team == "A" else session.side_b_xp
            after = xp_manager.apply(
                session, player.team, requested, side_a_char, side_b_char
            )
            applied = after - before

        player.heal_total += applied
        player.last_interaction = datetime.now(timezone.utc)
        db.add(
            BattleEvent(
                session_id=session.id,
                player_id=player.id,
                event_type="like",
                quantity=count,
                combo_count=1,
                xp_delta=applied,
                target_side=player.team,
                payload={"source": event.raw.get("provider", "simulator")},
            )
        )
        await db.flush()

        return {
            "type": "team_heart",
            "session_id": session.id,
            "player": self._player_payload(player, False),
            "count": count,
            "target_side": player.team,
            "heal": round(applied, 1),
            "xp": {"a": session.side_a_xp, "b": session.side_b_xp},
            "xp_max": {"a": side_a_char.xp_max, "b": side_b_char.xp_max},
            "teams": teams,
        }

    async def _handle_follow(
        self, db: AsyncSession, session: BattleSession, battle: Battle, event: LiveEvent
    ) -> dict:
        """A follow permanently enlarges this session's avatar and triples HP.

        Providers occasionally repeat social messages. ``player.followed`` is
        the idempotency guard, so one follow can never become 3x, then 9x.
        """
        player = await self._active_social_player(db, session, battle, event)
        if player is None or player.followed:
            return {}

        social = await settings_service.get(db, "social_actions")
        multiplier = max(1.0, float(social.get("follow_life_multiplier", 3)))
        base = player.power if player.power > 0 else float(social.get("follow_base_life", 100))
        previous = player.power
        player.power = base * multiplier
        player.peak_power = max(player.peak_power, player.power)
        player.followed = True
        player.eliminated = False
        player.heal_total += max(0.0, player.power - previous)
        player.last_interaction = datetime.now(timezone.utc)

        teams = None
        if battle.mode == "team_pvp":
            team_config = await settings_service.get(db, "team_battle")
            player.level = team_battle_manager.level_for(player.power, team_config)

        db.add(
            BattleEvent(
                session_id=session.id,
                player_id=player.id,
                event_type="follow",
                quantity=1,
                combo_count=1,
                xp_delta=player.power - previous,
                target_side=player.team,
                payload={
                    "multiplier": multiplier,
                    "previous_power": previous,
                    "source": event.raw.get("provider", "simulator"),
                },
            )
        )
        await db.flush()

        roster = (
            (await db.execute(select(Player).where(Player.session_id == session.id)))
            .scalars()
            .all()
        )
        if battle.mode == "team_pvp":
            teams = team_battle_manager.team_totals(roster)

        return {
            "type": "player_followed",
            "session_id": session.id,
            "player": self._player_payload(player, False),
            "previous_power": round(previous, 1),
            "power": round(player.power, 1),
            "multiplier": multiplier,
            "teams": teams,
            "armies": tank_war_manager.army_totals(roster)
            if battle.mode == "tank_war"
            else None,
        }

    @staticmethod
    async def _active_social_player(
        db: AsyncSession, session: BattleSession, battle: Battle, event: LiveEvent
    ) -> Player | None:
        player = (
            await db.execute(
                select(Player).where(
                    Player.session_id == session.id,
                    Player.user_id == event.user.id,
                )
            )
        ).scalar_one_or_none()
        if player is None or player.eliminated or player.queued:
            return None
        if battle.mode == "tank_war" and not player.team_selected:
            return None
        return player

    # ------------------------------------------------------------------
    # Team PvP mode (viewers fight each other instead of the characters)
    # ------------------------------------------------------------------

    async def _handle_gift_pvp(
        self, db: AsyncSession, session: BattleSession, battle: Battle, event: LiveEvent
    ) -> dict:
        gift = await self._resolve_gift(db, event)
        if gift is not None and not await gift_cache.allows(db, battle.id, gift):
            logger.info("gift_key=%s não faz parte desta batalha, ignorado", gift.gift_key)
            return {}
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
        """Viewers enlist by typing a keyword in chat ("A" or "B" by default).
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
        if battle.mode == "tank_war":
            player.team_selected = True

        queued = False
        if created or player.eliminated or player.power <= 0:
            if battle.mode == "tank_war" and await tank_war_manager.field_is_full(
                db, session.id, config, battle
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
        # In Eleições 2026 a viewer chooses their side explicitly in chat.
        # Gifts from someone who has not typed A or B do not create a player,
        # choose a random side, or change either candidate's score.
        existing = (
            await db.execute(
                select(Player).where(
                    Player.session_id == session.id, Player.user_id == event.user.id
                )
            )
        ).scalar_one_or_none()
        if existing is None or not existing.team_selected or existing.queued:
            return {}

        gift = await self._resolve_gift(db, event)
        if gift is not None and not await gift_cache.allows(db, battle.id, gift):
            logger.info("gift_key=%s não faz parte desta batalha, ignorado", gift.gift_key)
            return {}
        if gift is None or not gift.active:
            self._log_unknown_gift(event)
            return {}

        quantity = event.gift.quantity
        combo_count = combo_manager.register(session.id, event.user.id, gift.gift_key, quantity)
        combo_tier = gift_cache.combo_tier_for(combo_count)
        action = gift_rule_engine.resolve(gift, quantity, combo_count, combo_tier)
        config = await settings_service.get(db, "tank_war")

        # The team is fixed by the participant's A/B comment.
        team = existing.team

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
            if await tank_war_manager.field_is_full(db, session.id, config, battle):
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
                promoted = await tank_war_manager.promote_from_queue(db, session_id, config, battle)

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
            "followed": player.followed,
        }

    @staticmethod
    async def _existing_team(db: AsyncSession, session_id: str, user_id: str) -> str | None:
        """Which side this viewer already plays for, if they have played."""
        return (
            await db.execute(
                select(Player.team).where(
                    Player.session_id == session_id, Player.user_id == user_id
                )
            )
        ).scalar_one_or_none()

    async def _resolve_gift(self, db: AsyncSession, event: LiveEvent):
        """Use a provider-specific, immutable ID for real LIVE events.

        Simulator events deliberately keep using the friendly ``gift_key``.
        TikTok events, however, must never be matched by the translated gift
        name: names vary by locale while TikTok's numeric gift ID is stable.
        """
        if event.gift is None:
            return None

        provider = event.raw.get("provider")
        if provider in (None, "", "simulator"):
            # The simulator addresses gifts by their friendly key unless it is
            # deliberately replaying a platform event (see simulate_catalog_gift).
            by_key = gift_cache.get(event.gift.id)
            if by_key is not None:
                return by_key
            return gift_cache.get_platform("simulator", event.gift.id)

        return gift_cache.get_platform(provider, event.gift.id)

    @staticmethod
    def _log_unknown_gift(event: LiveEvent) -> None:
        """A gift with no rule is captured but never fires an attack.

        Section 6: the gift is already in the catalogue by the time we get
        here, so the only thing left to do is tell the operator it is sitting
        there unconfigured.
        """
        if event.gift is None:
            return
        provider = event.raw.get("provider")
        if provider not in (None, "", "simulator"):
            logger.warning(
                "presente sem regra: plataforma=%s id=%s nome=%s -- configure em Presentes da LIVE",
                provider,
                event.gift.id,
                event.gift.name,
            )
            admin_channel.broadcast_soon(
                {
                    "type": "gift_catalog:unconfigured",
                    "platform": provider,
                    "gift_id": str(event.gift.id),
                    "name": event.gift.name,
                }
            )
            return
        logger.warning("unknown or inactive gift_key=%s ignored", event.gift.id)


game_pipeline = GamePipeline()
