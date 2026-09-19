from __future__ import annotations

import io
import logging

import discord
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("hrcc.cert")

WIDTH = 1200
HEIGHT = 800

BG_COLOR = (255, 255, 255)
BORDER_COLOR = (0, 102, 204)
ACCENT_COLOR = (0, 102, 204)
TEXT_COLOR = (30, 30, 30)
SUBTITLE_COLOR = (100, 100, 100)
WATERMARK_COLOR = (220, 220, 220)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _load_font_regular(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _center_text(draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, fill: tuple[int, ...]) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (WIDTH - tw) // 2
    draw.text((x, y), text, fill=fill, font=font)


def generate_certificate_preview(
    *,
    name: str,
    college_name: str = "",
    event_name: str = "Campus Event",
    rank: int = 1,
    date: str = "",
) -> bytes:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.rectangle([(20, 20), (WIDTH - 21, HEIGHT - 21)], outline=BORDER_COLOR, width=4)
    draw.rectangle([(30, 30), (WIDTH - 31, HEIGHT - 31)], outline=ACCENT_COLOR, width=1)

    draw.rectangle([(0, 0), (WIDTH, 8)], fill=ACCENT_COLOR)
    draw.rectangle([(0, HEIGHT - 8), (WIDTH, HEIGHT)], fill=ACCENT_COLOR)

    font_title = _load_font(36)
    font_subtitle = _load_font_regular(20)
    font_name = _load_font(48)
    font_detail = _load_font_regular(22)
    font_watermark = _load_font_regular(14)

    _center_text(draw, 60, "HACKERRANK CAMPUS CREW", font_title, ACCENT_COLOR)
    _center_text(draw, 110, "Certificate of Achievement", font_subtitle, SUBTITLE_COLOR)

    draw.line([(200, 160), (WIDTH - 200, 160)], fill=ACCENT_COLOR, width=2)

    _center_text(draw, 190, "This certificate is proudly presented to", font_detail, SUBTITLE_COLOR)
    _center_text(draw, 250, name, font_name, TEXT_COLOR)

    if college_name:
        _center_text(draw, 320, college_name, font_detail, SUBTITLE_COLOR)

    draw.line([(200, 370), (WIDTH - 200, 370)], fill=ACCENT_COLOR, width=2)

    rank_labels = {1: "1st Place", 2: "2nd Place", 3: "3rd Place"}
    rank_text = rank_labels.get(rank, f"Rank #{rank}")

    _center_text(draw, 400, f"for outstanding performance — {rank_text}", font_detail, TEXT_COLOR)
    _center_text(draw, 440, f"in {event_name}", font_subtitle, ACCENT_COLOR)

    if date:
        _center_text(draw, 500, f"Date: {date}", font_detail, SUBTITLE_COLOR)

    _center_text(draw, 580, "___________________________          ___________________________", font_detail, TEXT_COLOR)
    _center_text(draw, 620, "Program Manager                              Technical Lead", font_watermark, SUBTITLE_COLOR)
    _center_text(draw, 650, "Sanskruti                                             Sreesanth", font_detail, SUBTITLE_COLOR)

    _center_text(draw, 740, "HackerRank Campus Crew | hackerrank.com", font_watermark, WATERMARK_COLOR)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()


def build_cert_preview_file(
    *,
    name: str,
    college_name: str = "",
    event_name: str = "Campus Event",
    rank: int = 1,
    date: str = "",
) -> discord.File:
    png_bytes = generate_certificate_preview(
        name=name, college_name=college_name, event_name=event_name, rank=rank, date=date,
    )
    return discord.File(io.BytesIO(png_bytes), filename="certificate_preview.png")
