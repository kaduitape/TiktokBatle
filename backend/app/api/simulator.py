import random

from fastapi import APIRouter, Depends

from app.core.auth import require_admin
from app.providers.simulation_provider import simulation_provider
from app.schemas.schemas import SimulateGiftRequest

router = APIRouter(prefix="/api/simulator", tags=["simulator"])

_FAKE_USERNAMES = [
    "carlos", "ana", "joao", "maria", "pedro", "lucas", "julia", "bruno",
    "camila", "rafael", "fernanda", "gustavo", "larissa", "thiago", "bianca",
]


@router.post("/gift")
async def simulate_gift(body: SimulateGiftRequest, _: str = Depends(require_admin)):
    """Executes exactly the same pipeline a real TikTok gift would trigger
    (spec section 45: no separate simulated-vs-real animation logic)."""
    user_id = f"sim-{body.username}"
    await simulation_provider.simulate_gift(
        session_id=body.session_id,
        user_id=user_id,
        username=body.username,
        gift_key=body.gift_key,
        quantity=body.quantity,
        nickname=body.nickname or body.username,
        avatar_url=body.avatar_url,
    )
    return {"ok": True}


@router.post("/join")
async def simulate_join(session_id: str, username: str | None = None, _: str = Depends(require_admin)):
    name = username or random.choice(_FAKE_USERNAMES) + str(random.randint(1, 9999))
    await simulation_provider.simulate_join(
        session_id=session_id,
        user_id=f"sim-{name}",
        username=name,
        nickname=name,
        avatar_url=f"https://i.pravatar.cc/150?u={name}",
    )
    return {"ok": True, "username": name}


@router.post("/comment")
async def simulate_comment(
    session_id: str, text: str, username: str | None = None, _: str = Depends(require_admin)
):
    """Tank war mode enlists viewers from chat, so the simulator needs to be
    able to say things as well as send gifts."""
    name = username or random.choice(_FAKE_USERNAMES) + str(random.randint(1, 9999))
    await simulation_provider.simulate_comment(
        session_id=session_id,
        user_id=f"sim-{name}",
        username=name,
        text=text,
        nickname=name,
        avatar_url=f"https://i.pravatar.cc/150?u={name}",
    )
    return {"ok": True, "username": name, "text": text}


@router.post("/stress")
async def simulate_stress(
    session_id: str, gift_keys: list[str], user_count: int = 100, _: str = Depends(require_admin)
):
    """Section 46: SIMULAR LIVE LOTADA. Generates a burst of joins and
    gifts through the normal pipeline so FPS/latency/queue depth can be
    observed under load."""
    for i in range(user_count):
        name = f"stress{i}_{random.randint(1, 999999)}"
        await simulation_provider.simulate_join(
            session_id=session_id,
            user_id=f"sim-{name}",
            username=name,
            nickname=name,
            avatar_url=f"https://i.pravatar.cc/150?u={name}",
        )
        if gift_keys:
            await simulation_provider.simulate_gift(
                session_id=session_id,
                user_id=f"sim-{name}",
                username=name,
                gift_key=random.choice(gift_keys),
                quantity=random.choice([1, 1, 1, 5, 10]),
                nickname=name,
                avatar_url=f"https://i.pravatar.cc/150?u={name}",
            )
    return {"ok": True, "spawned": user_count}
