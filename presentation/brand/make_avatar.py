"""Render the AETHER wordmark as a square profile picture.

Two variants, because an avatar has two jobs. The wordmark reads on a profile
header at 200px and up; the monogram is what survives a 32px comment thread.

Both are laid out inside the inscribed circle, since most platforms crop a square
avatar to a circle and anything near the corners is lost.

.. rubric:: Why the mark is composited rather than positioned

Centring on advance widths puts the mark visibly off centre: an advance includes
the glyph's side bearings, and a letter-spaced run also carries trailing tracking
after its last glyph. So the mark is drawn onto its own transparent layer, its
real ink bounding box measured, and that box centred. What gets centred is the
ink a reader sees, not the metrics the font declares.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 1024
GROUND = (0, 0, 0)
INK = (237, 237, 237)
ACCENT = (79, 195, 174)

FONT = "C:/Windows/Fonts/bahnschrift.ttf"
OUT = Path("D:/ClauseCode1/Ather-derivatives/presentation/brand")

#: Optical centre sits slightly above geometric centre — a mark centred by
#: measurement reads as though it has slipped downwards.
OPTICAL_LIFT = 0.014


def light(px: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(FONT, px)
    font.set_variation_by_name("Light")
    return font


def tracked_advance(draw: ImageDraw.ImageDraw, text: str, font, tracking: float) -> float:
    total = 0.0
    for index, char in enumerate(text):
        total += draw.textlength(char, font=font)
        if index < len(text) - 1:
            total += tracking
    return total


def draw_tracked(draw, x: float, y: float, text: str, font, tracking: float, fill) -> None:
    for char in text:
        draw.text((x, y), char, font=font, fill=fill, anchor="ls")
        x += draw.textlength(char, font=font) + tracking


def ground() -> Image.Image:
    """Pure black.

    The application's shell carries a faint overhead wash, and it was tried here
    first. Approximated with concentric ellipses it bands: at avatar sizes the
    steps read as a hard horizontal edge near the top of the frame, which looks
    like a compression artefact rather than a gradient. A flat ground has no such
    failure mode, and matches the wordmark as it was supplied.
    """
    return Image.new("RGB", (SIZE, SIZE), GROUND)


def fit(draw, text: str, target: float, tracking_ratio: float) -> tuple[ImageFont.FreeTypeFont, float]:
    """Size the glyphs so the tracked run spans `target`, tracking scaling with them."""
    px = 200
    for _ in range(60):
        font = light(px)
        width = tracked_advance(draw, text, font, px * tracking_ratio)
        if width <= 0:
            break
        if abs(width - target) < 1:
            break
        px = max(8, int(px * target / width))
    font = light(px)
    return font, px * tracking_ratio


def compose(text: str, span: float, tracking_ratio: float, rule_width: float,
            rule_gap: float, rule_thickness: float) -> Image.Image:
    """Draw the mark on a transparent layer, then centre its ink on the ground."""
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)

    font, tracking = fit(pen, text, SIZE * span, tracking_ratio)
    draw_tracked(pen, SIZE * 0.1, SIZE * 0.55, text, font, tracking, INK + (255,))

    box = layer.getbbox()
    if box is None:  # pragma: no cover - a font with no glyphs for the text
        raise RuntimeError(f"Nothing rendered for {text!r}.")
    left, top, right, bottom = box

    # The rule hangs from the text's ink, not from a baseline, so the gap is the
    # gap a reader actually sees.
    width = SIZE * rule_width
    thickness = max(2, round(SIZE * rule_thickness))
    rule_top = bottom + SIZE * rule_gap
    centre_x = (left + right) / 2
    pen.rectangle(
        [centre_x - width / 2, rule_top, centre_x + width / 2, rule_top + thickness],
        fill=ACCENT + (255,),
    )

    box = layer.getbbox()
    left, top, right, bottom = box
    dx = round(SIZE / 2 - (left + right) / 2)
    dy = round(SIZE * (0.5 - OPTICAL_LIFT) - (top + bottom) / 2)

    shifted = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    shifted.paste(layer.crop(box), (left + dx, top + dy))

    image = ground()
    image.paste(shifted, (0, 0), shifted)
    return image


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    variants = {
        # Wide and quiet. 0.63 of the width keeps it clear of a circle crop.
        "aether-avatar-wordmark": compose(
            "AETHER", span=0.63, tracking_ratio=0.30,
            rule_width=0.115, rule_gap=0.055, rule_thickness=0.0045,
        ),
        # Fewer, larger glyphs — the only thing that reads at 32px.
        "aether-avatar-monogram": compose(
            "AE", span=0.46, tracking_ratio=0.16,
            rule_width=0.13, rule_gap=0.065, rule_thickness=0.007,
        ),
    }
    for name, image in variants.items():
        image.save(OUT / f"{name}.png")
        image.resize((400, 400), Image.LANCZOS).save(OUT / f"{name}-400.png")
        image.resize((32, 32), Image.LANCZOS).save(OUT / f"{name}-32.png")
        print(f"  {name}.png  {SIZE}x{SIZE}  (+400, +32)")


if __name__ == "__main__":
    main()
