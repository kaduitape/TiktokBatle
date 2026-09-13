#!/usr/bin/env python3
"""Monta uma folha de sprites a partir de imagens soltas.

Geradores de imagem entregam uma pose por arquivo; o jogo quer as poses lado a
lado numa grade de células do mesmo tamanho. Este script faz essa junção e no
fim imprime exatamente os números que devem ser digitados em
Admin -> Personagens.

    python scripts/make_spritesheet.py pose1.png pose2.png pose3.png -o lula.png

Se você tem uma chave de imagem configurada, o painel faz tudo isso sozinho em
Admin -> Gerar sprites; este script serve para poses que você já tem em mãos.
"""
import argparse
import sys
from pathlib import Path

# A montagem mora no backend para que o painel e este script produzam
# exatamente a mesma grade -- o jogo fatia a imagem dividindo pela grade, então
# qualquer divergência apareceria como o personagem tremendo entre os quadros.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

try:
    from PIL import Image

    from app.services.sprite_sheet import compose_sheet
except ImportError:
    sys.exit("Instale a dependência primeiro:  pip install Pillow")


def parse_cell(value: str) -> tuple[int, int]:
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("use o formato LARGURAxALTURA, ex: 512x768")


def main() -> None:
    ap = argparse.ArgumentParser(description="Monta uma folha de sprites para o jogo.")
    ap.add_argument("images", nargs="+", help="as poses, na ordem da animação")
    ap.add_argument("-o", "--output", default="spritesheet.png")
    ap.add_argument("--columns", type=int, default=0, help="poses por linha (0 = todas numa linha)")
    ap.add_argument("--cell", type=parse_cell, default=None, help="tamanho da célula, ex: 512x768")
    args = ap.parse_args()

    frames = [Image.open(path) for path in args.images]
    layout = compose_sheet(frames, columns=args.columns, cell=args.cell)
    Path(args.output).write_bytes(layout.png)

    print(
        f"\nFolha salva em {args.output}  "
        f"({layout.width}x{layout.height}, célula {layout.frame_width}x{layout.frame_height})"
    )
    print("\nEm Admin -> Personagens, suba essa imagem e preencha:")
    print(f"  Colunas ............. {layout.columns}")
    print(f"  Linhas .............. {layout.rows}")
    incomplete = layout.frame_count != layout.columns * layout.rows
    print(
        f"  Quadros ............. {layout.frame_count}"
        + ("  (grade tem células vazias no fim)" if incomplete else "")
    )
    print("  Quadros por segundo . 8   (6-10 costuma ficar bom)")


if __name__ == "__main__":
    main()
