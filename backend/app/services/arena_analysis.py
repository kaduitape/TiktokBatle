"""Checks a battle's configuration before it goes live.

Everything here is a concrete, checkable property of the battle the admin
configured -- art that is missing, numbers that make the match unwatchable,
settings that read as pay-to-win. It is deliberately not an AI review and not
a compliance ruling: it cannot see the stream, and no checklist can promise a
platform will not act. It catches the mistakes that are visible from the data.
"""
from dataclasses import asdict, dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Battle, BattleGift, Character, Gift

Severity = Literal["alto", "medio", "dica"]


@dataclass
class Finding:
    severity: Severity
    area: str
    problem: str
    fix: str


def _art(character: Character, side: str) -> list[Finding]:
    out: list[Finding] = []
    if not character.image_url:
        out.append(
            Finding(
                "alto",
                f"Lado {side}",
                f"{character.name} está sem imagem: entra na arena como um emoji genérico.",
                "Suba o desenho em Admin → Personagens, ou gere um em Gerar sprites.",
            )
        )
    if character.sprite_columns == 0:
        out.append(
            Finding(
                "dica",
                f"Lado {side}",
                f"{character.name} é um desenho parado.",
                "Uma folha de sprites com 4 a 6 poses deixa o personagem vivo na tela.",
            )
        )
    if not character.hit_image_url:
        out.append(
            Finding(
                "dica",
                f"Lado {side}",
                f"{character.name} não reage quando leva dano.",
                "Cadastre a imagem de dano: o espectador vê o efeito do presente dele.",
            )
        )
    return out


async def analyse(db: AsyncSession, battle: Battle) -> dict:
    findings: list[Finding] = []

    side_a = await db.get(Character, battle.side_a_character_id)
    side_b = await db.get(Character, battle.side_b_character_id)

    if side_a and side_b:
        if side_a.id == side_b.id:
            findings.append(
                Finding(
                    "alto",
                    "Personagens",
                    "Os dois lados são o mesmo personagem.",
                    "Escolha personagens diferentes para Lado A e Lado B.",
                )
            )
        elif side_a.image_url and side_a.image_url == side_b.image_url:
            findings.append(
                Finding(
                    "alto",
                    "Personagens",
                    "Os dois lados usam a mesma imagem: ninguém distingue os times.",
                    "Suba uma arte diferente para cada lado.",
                )
            )
        findings += _art(side_a, "A") + _art(side_b, "B")

        if abs(side_a.xp_max - side_b.xp_max) > max(side_a.xp_max, side_b.xp_max) * 0.1:
            findings.append(
                Finding(
                    "medio",
                    "Equilíbrio",
                    f"Vidas diferentes: {side_a.xp_max:,} contra {side_b.xp_max:,}."
                    .replace(",", "."),
                    "Deixe as duas iguais, ou o lado mais fraco perde sempre e o público desiste.",
                )
            )

    gifts = (await db.execute(select(Gift).where(Gift.active.is_(True)))).scalars().all()
    selected = (
        (await db.execute(select(BattleGift.gift_id).where(BattleGift.battle_id == battle.id)))
        .scalars()
        .all()
    )
    if selected:
        gifts = [g for g in gifts if g.id in set(selected)]

    if not gifts:
        findings.append(
            Finding(
                "alto",
                "Presentes",
                "Nenhum presente ativo nesta batalha: o público não tem como jogar.",
                "Selecione ao menos um presente em Batalhas → Presentes desta batalha.",
            )
        )
    else:
        cheapest = min(g.coins or 1 for g in gifts)
        dearest = max(g.coins or 1 for g in gifts)
        if cheapest > 10:
            findings.append(
                Finding(
                    "medio",
                    "Presentes",
                    f"O presente mais barato custa {cheapest} moedas.",
                    "Inclua um presente de 1 moeda: quem não gasta também precisa conseguir "
                    "participar, senão a live vira só vitrine de venda.",
                )
            )
        if dearest >= cheapest * 400:
            findings.append(
                Finding(
                    "medio",
                    "Equilíbrio",
                    f"O presente mais caro vale {dearest // max(1, cheapest)}x o mais barato.",
                    "Uma diferença muito grande faz uma pessoa decidir a partida sozinha e "
                    "desanima o resto do público.",
                )
            )

    if battle.mode == "tank_war":
        if not (side_a and side_b) or min(side_a.xp_max, side_b.xp_max) < 100_000:
            findings.append(
                Finding(
                    "medio",
                    "Guerra de Tanques",
                    "Os chefões têm pouca vida para este modo.",
                    "Abaixo de 100.000 a partida acaba em poucos presentes. O padrão do modo "
                    "é 1.500.000.",
                )
            )

    if battle.max_players > 200:
        findings.append(
            Finding(
                "dica",
                "Arena",
                f"Limite de {battle.max_players} participantes na tela.",
                "Acima de ~100 os avatares ficam pequenos demais para alguém se reconhecer.",
            )
        )

    if not battle.auto_restart and not battle.battle_time_seconds:
        findings.append(
            Finding(
                "dica",
                "Ritmo",
                "Sem tempo de batalha e sem reinício automático.",
                "Uma partida que nunca termina não dá clímax. Defina um tempo ou ligue o "
                "reinício automático para ter rodadas.",
            )
        )

    order = {"alto": 0, "medio": 1, "dica": 2}
    findings.sort(key=lambda f: order[f.severity])
    return {
        "battle_id": battle.id,
        "battle_name": battle.name,
        "counts": {
            "alto": sum(1 for f in findings if f.severity == "alto"),
            "medio": sum(1 for f in findings if f.severity == "medio"),
            "dica": sum(1 for f in findings if f.severity == "dica"),
        },
        "findings": [asdict(f) for f in findings],
    }
