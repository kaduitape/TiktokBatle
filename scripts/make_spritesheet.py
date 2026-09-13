#!/usr/bin/env python3
"""Monta uma folha de sprites a partir de imagens soltas.

Geradores de imagem entregam uma pose por arquivo; o jogo quer as poses lado a
lado numa grade de células do mesmo tamanho. Este script faz essa junção: cada
imagem vira uma célula, centralizada e alinhada pelo pé, e no fim ele imprime
exatamente os números que devem ser digitados em Admin -> Personagens.

    python scripts/make_spritesheet.py pose1.png pose2.png pose3.png -o lula.png

Opções úteis:
    --columns 4     quantas poses por linha (padrão: todas numa linha só)
    --cell 512x768  força o tamanho da célula (padrão: a maior imagem recortada)
"""
import argparse
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Instale a dependência primeiro:  pip install Pillow")

# Limite seguro de textura para as GPUs que rodam OBS; acima disso algumas
# placas se recusam a carregar a imagem e o personagem some.
MAX_SIDE = 4096


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

    frames = []
    for path in args.images:
        img = Image.open(path).convert("RGBA")
        # Recorta o vazio em volta para que todas as poses fiquem no mesmo
        # enquadramento, mesmo que a IA tenha deixado margens diferentes.
        frames.append(img.crop(img.getbbox() or (0, 0, img.width, img.height)))

    if args.cell:
        cell_w, cell_h = args.cell
    else:
        cell_w = max(f.width for f in frames)
        cell_h = max(f.height for f in frames)

    columns = args.columns if args.columns > 0 else len(frames)
    rows = -(-len(frames) // columns)  # divisão para cima

    sheet_w, sheet_h = cell_w * columns, cell_h * rows
    if sheet_w > MAX_SIDE or sheet_h > MAX_SIDE:
        scale = min(MAX_SIDE / sheet_w, MAX_SIDE / sheet_h)
        cell_w, cell_h = int(cell_w * scale), int(cell_h * scale)
        sheet_w, sheet_h = cell_w * columns, cell_h * rows
        print(f"aviso: folha maior que {MAX_SIDE}px; célula reduzida para {cell_w}x{cell_h}")

    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        ratio = min(cell_w / frame.width, cell_h / frame.height)
        resized = frame.resize((max(1, int(frame.width * ratio)), max(1, int(frame.height * ratio))), Image.LANCZOS)
        col, row = i % columns, i // columns
        # Centralizado na horizontal e encostado na base: mantém o personagem
        # plantado no chão em vez de flutuar de um quadro para o outro.
        x = col * cell_w + (cell_w - resized.width) // 2
        y = row * cell_h + (cell_h - resized.height)
        sheet.paste(resized, (x, y), resized)

    sheet.save(args.output)

    print(f"\nFolha salva em {args.output}  ({sheet_w}x{sheet_h}, célula {cell_w}x{cell_h})")
    print("\nEm Admin -> Personagens, suba essa imagem e preencha:")
    print(f"  Colunas ............. {columns}")
    print(f"  Linhas .............. {rows}")
    print(f"  Quadros ............. {len(frames)}" + ("  (grade tem células vazias no fim)" if len(frames) != columns * rows else ""))
    print("  Quadros por segundo . 8   (6-10 costuma ficar bom)")


if __name__ == "__main__":
    main()
