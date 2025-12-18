#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# 2K vertical 9:16 (QHD portrait)
W, H = 1440, 2560

BLUE = (18, 61, 150)
TEXT = (25, 25, 25)

# Layout boxes in (x, y, w, h) for 1440x2560
# Tune once to match your template exactly.
BOX = {
    "month_cn":   (120, 120,  700,  90),
    "month_en":   (120, 210,  700, 110),
    "lunar":      (120, 330,  900,  80),
    "weekday":    (120, 410,  900,  80),
    "day_big":    (880,  90,  480,  360),

    # Middle long text area (your “image + quote” becomes pure text)
    "main_text":  (120, 560,  1200, 1500),

    "footer":     (120, 2160, 1200, 200),
}

def load_font(font_path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path, size=size, index=index)

def tokenize_mixed_text(s: str):
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    tokens = []
    for para in s.split("\n"):
        if para == "":
            tokens.append("\n")
            continue
        pieces = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+|[^\sA-Za-z0-9\u4e00-\u9fff]", para)
        tokens.extend(pieces)
        tokens.append("\n")
    if tokens:
        tokens.pop()
    return tokens

def wrap_tokens_to_width(draw: ImageDraw.ImageDraw, tokens, font, max_width: int):
    lines, cur = [], ""

    def text_w(t: str) -> int:
        if not t:
            return 0
        b = draw.textbbox((0, 0), t, font=font)
        return b[2] - b[0]

    for tok in tokens:
        if tok == "\n":
            lines.append(cur.rstrip())
            cur = ""
            continue

        if cur == "" and tok == " ":
            continue

        cand = (cur + tok) if cur else tok
        if text_w(cand) <= max_width:
            cur = cand
            continue

        if cur:
            lines.append(cur.rstrip())
            cur = tok.lstrip()
        else:
            # hard-break extremely long token
            buf = ""
            for ch in tok:
                c2 = buf + ch
                if text_w(c2) <= max_width:
                    buf = c2
                else:
                    if buf:
                        lines.append(buf)
                    buf = ch
            cur = buf

    if cur != "":
        lines.append(cur.rstrip())

    while lines and lines[-1] == "":
        lines.pop()

    return lines

def fit_text_in_box(draw, text: str, font_path: str, font_index: int,
                    box_w: int, box_h: int,
                    start_size: int, min_size: int,
                    line_spacing: int):
    tokens = tokenize_mixed_text(text)

    for size in range(start_size, min_size - 1, -2):
        font = load_font(font_path, size=size, index=font_index)
        lines = wrap_tokens_to_width(draw, tokens, font, box_w)

        ascent, descent = font.getmetrics()
        line_h = ascent + descent + line_spacing
        total_h = len(lines) * line_h
        if total_h <= box_h:
            return font, lines

    # truncate at min size
    font = load_font(font_path, size=min_size, index=font_index)
    lines = wrap_tokens_to_width(draw, tokens, font, box_w)

    ascent, descent = font.getmetrics()
    line_h = ascent + descent + line_spacing
    max_lines = max(1, box_h // line_h)
    truncated = len(lines) > max_lines
    lines = lines[:max_lines]

    if truncated and lines:
        last = lines[-1]
        ell = "…"
        while True:
            b = draw.textbbox((0, 0), last + ell, font=font)
            if (b[2] - b[0]) <= box_w or last == "":
                break
            last = last[:-1]
        lines[-1] = (last + ell) if last else ell

    return font, lines

def draw_lines(img, box, lines, font, fill, align="left", line_spacing=10):
    x, y, w, h = box
    draw = ImageDraw.Draw(img)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + line_spacing

    yy = y
    for line in lines:
        if yy + line_h > y + h:
            break
        if align == "right":
            b = draw.textbbox((0, 0), line, font=font)
            tw = b[2] - b[0]
            xx = x + w - tw
        elif align == "center":
            b = draw.textbbox((0, 0), line, font=font)
            tw = b[2] - b[0]
            xx = x + (w - tw) // 2
        else:
            xx = x
        draw.text((xx, yy), line, font=font, fill=fill)
        yy += line_h

def render_one(row: dict, bg_path: str, font_cn: str, font_en: str,
               font_index_cn: int = 0, font_index_en: int = 0) -> Image.Image:
    bg = Image.open(bg_path).convert("RGB").resize((W, H))
    draw = ImageDraw.Draw(bg)

    # Fonts (tune sizes as you like)
    f_month_cn = load_font(font_cn, 56, font_index_cn)
    f_month_en = load_font(font_en, 76, font_index_en)
    f_small_cn = load_font(font_cn, 50, font_index_cn)
    f_small_en = load_font(font_en, 50, font_index_en)
    f_day_big  = load_font(font_en, 280, font_index_en)

    def as_lines(s): return [str(s or "").strip()]

    draw_lines(bg, BOX["month_cn"], as_lines(row.get("month_cn","")), f_month_cn, BLUE)
    draw_lines(bg, BOX["month_en"], as_lines(row.get("month_en","")), f_month_en, BLUE)

    lunar = (row.get("lunar","") or "").strip()
    solar = (row.get("solar_term","") or "").strip()
    lunar_line = lunar if not solar else f"{lunar} · {solar}"
    draw_lines(bg, BOX["lunar"], as_lines(lunar_line), f_small_cn, BLUE)

    weekday = f"{(row.get('weekday_en','') or '').strip()}  {(row.get('weekday_cn','') or '').strip()}".strip()
    draw_lines(bg, BOX["weekday"], as_lines(weekday), f_small_en, BLUE)

    day = str(row.get("day","") or "").strip()
    draw_lines(bg, BOX["day_big"], [day], f_day_big, BLUE, align="right", line_spacing=0)

    # Main long text: wrap + auto-fit
    x, y, w, h = BOX["main_text"]
    main_text = (row.get("main_text","") or "").strip()
    main_font, main_lines = fit_text_in_box(
        draw, main_text, font_path=font_cn, font_index=font_index_cn,
        box_w=w, box_h=h,
        start_size=72, min_size=34,
        line_spacing=22
    )
    draw_lines(bg, BOX["main_text"], main_lines, main_font, TEXT, align="left", line_spacing=22)

    footer = (row.get("footer","") or "").strip()
    if footer:
        f_footer = load_font(font_cn, 44, font_index_cn)
        draw_lines(bg, BOX["footer"], [footer], f_footer, BLUE, align="center", line_spacing=10)

    return bg

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--bg", required=True, help="paper texture background png/jpg")
    ap.add_argument("--out", required=True, help="output frames dir")
    ap.add_argument("--font-cn", required=True, help="Chinese font .ttf/.ttc")
    ap.add_argument("--font-en", required=True, help="English font .ttf/.ttc")
    ap.add_argument("--font-index-cn", type=int, default=0)
    ap.add_argument("--font-index-en", type=int, default=0)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.csv, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    for i, row in enumerate(rows, 1):
        date = (row.get("date") or "").strip()
        if not date:
            raise ValueError(f"Row {i} missing 'date'")
        img = render_one(row, args.bg, args.font_cn, args.font_en, args.font_index_cn, args.font_index_en)
        img.save(out_dir / f"{date}.png", "PNG")
        print(f"[{i}/{len(rows)}] {date}.png")

    print("Done.")

if __name__ == "__main__":
    main()