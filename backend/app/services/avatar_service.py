from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Battle, Player


class AvatarService:
    """Owns the '1 user = 1 ball' rule (section 30) and the max-players cap
    with oldest-inactive eviction (section 29). Never evicts a player mid
    interaction because eviction only runs before creating a brand new
    player, not on an existing one being reused."""

    @staticmethod
    async def get_or_create_player(
        db: AsyncSession,
        session_id: str,
        battle: Battle,
        user_id: str,
        username: str,
        nickname: str | None,
        avatar_url: str | None,
        team: str,
    ) -> tuple[Player, bool]:
        existing = None
        if battle.one_ball_per_user:
            existing = (
                await db.execute(
                    select(Player).where(
                        Player.session_id == session_id, Player.user_id == user_id
                    )
                )
            ).scalar_one_or_none()

        if existing:
            existing.nickname = nickname or existing.nickname
            existing.avatar_url = avatar_url or existing.avatar_url
            return existing, False

        await AvatarService._enforce_capacity(db, session_id, battle.max_players)

        player = Player(
            session_id=session_id,
            user_id=user_id,
            username=username,
            nickname=nickname,
            avatar_url=avatar_url,
            team=team,
        )
        db.add(player)
        await db.flush()
        return player, True

    @staticmethod
    async def _enforce_capacity(db: AsyncSession, session_id: str, max_players: int) -> None:
        count = (
            await db.execute(
                select(func.count()).select_from(Player).where(Player.session_id == session_id)
            )
        ).scalar_one()

        if count < max_players:
            return

        overflow = count - max_players + 1
        oldest = (
            (
                await db.execute(
                    select(Player)
                    .where(Player.session_id == session_id)
                    .order_by(Player.last_interaction.asc())
                    .limit(overflow)
                )
            )
            .scalars()
            .all()
        )
        for p in oldest:
            await db.delete(p)


avatar_service = AvatarService()
