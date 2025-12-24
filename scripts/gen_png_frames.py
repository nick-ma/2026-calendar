#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# 2K vertical 9:16 (QHD portrait)
W, H = 1440, 2560

BLUE = (100, 150, 255)  # Lighter blue for better visibility
TEXT = (255, 255, 255)  # White for maximum contrast on dark background
HEADER_COLOR = (220, 220, 255)  # Light blue-white for headers

# Layout boxes in (x, y, w, h) for 1440x2560
# Layout based on reference: day number top-left, month info top-right, quote center, footer bottom
BOX = {
    # Top-left: Large red day number
    "day_big":    (120, 120,  500,  500),
    
    # Top-right: Month and date info
    "month_cn":   (800, 120,  520,  80),   # Chinese month
    "month_en":   (800, 200,  520,  80),   # English month
    "weekday":    (800, 280,  520,  70),   # Weekday
    "lunar":      (800, 350,  520,  70),   # Lunar date
    
    # Center: Main quote text
    "main_text":  (120, 600,  1200, 1400),
    
    # Bottom: Footer
    "footer":     (120, 2300, 1200, 200),
}

def load_font(font_path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path, size=size, index=index)

def tokenize_mixed_text(s: str):
    """Tokenize text while preserving spaces and word boundaries."""
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    tokens = []
    for para in s.split("\n"):
        if para == "":
            tokens.append("\n")
            continue
        # Split by whitespace but keep the spaces
        # This regex matches: Chinese chars, English words, punctuation, or spaces
        # We'll use a simpler approach: split by spaces and add them back
        words = para.split(" ")
        for i, word in enumerate(words):
            if word:
                # Split word into Chinese chars, English words, and punctuation
                word_parts = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+|[^\sA-Za-z0-9\u4e00-\u9fff]+", word)
                tokens.extend(word_parts)
            # Add space after each word except the last one in the paragraph
            if i < len(words) - 1:
                tokens.append(" ")
        tokens.append("\n")
    if tokens:
        tokens.pop()  # Remove trailing newline
    return tokens

def wrap_tokens_to_width(draw: ImageDraw.ImageDraw, tokens, font, max_width: int):
    """Wrap tokens to fit width while preserving spaces."""
    lines, cur = [], ""

    def text_w(t: str) -> int:
        if not t:
            return 0
        b = draw.textbbox((0, 0), t, font=font)
        return b[2] - b[0]

    for tok in tokens:
        if tok == "\n":
            if cur.strip():  # Only add non-empty lines
                lines.append(cur.rstrip())
            cur = ""
            continue

        # Try adding the token to current line
        cand = cur + tok if cur else tok
        
        # If it fits, add it
        if text_w(cand) <= max_width:
            cur = cand
            continue

        # Doesn't fit - need to wrap
        if cur.strip():  # If current line has content, save it
            lines.append(cur.rstrip())
            cur = ""
        
        # Handle the token that doesn't fit
        if tok == " ":  # If it's just a space, skip it
            continue
        
        # Check if token itself is too long (hard break)
        if text_w(tok) > max_width:
            # Break long token character by character
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
        else:
            # Token fits on its own, start new line
            cur = tok

    # Add remaining content
    if cur.strip():
        lines.append(cur.rstrip())

    # Remove empty lines
    lines = [line for line in lines if line.strip()]

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
        if not line.strip():  # Skip empty lines
            continue
        if yy + line_h > y + h:
            break
        if align == "right":
            b = draw.textbbox((0, 0), line, font=font)
            tw = b[2] - b[0]
            xx = max(x, x + w - tw)  # Ensure xx >= x
        elif align == "center":
            b = draw.textbbox((0, 0), line, font=font)
            tw = b[2] - b[0]
            xx = x + max(0, (w - tw) // 2)  # Ensure xx >= x
        else:
            xx = x
        # Use textbbox to get proper y position including baseline
        bbox = draw.textbbox((xx, yy), line, font=font)
        draw.text((xx, yy), line, font=font, fill=fill)
        yy += line_h

def render_one(row: dict, bg_path: str, font_cn: str, font_en: str,
               font_index_cn: int = 0, font_index_en: int = 0) -> Image.Image:
    bg = Image.open(bg_path).convert("RGB").resize((W, H))
    draw = ImageDraw.Draw(bg)

    # Fonts - adjusted sizes for the new layout
    f_month_cn = load_font(font_cn, 56, font_index_cn)  # Chinese month
    f_month_en = load_font(font_en, 48, font_index_en)  # English month
    f_small_cn = load_font(font_cn, 40, font_index_cn)  # For weekday and lunar
    f_small_en = load_font(font_en, 40, font_index_en)  # For weekday
    f_day_big  = load_font(font_en, 400, font_index_en)  # Large day number

    def as_lines(s): return [str(s or "").strip()]

    # Draw large day number in top-left
    day = str(row.get("day","") or "").strip()
    if day:
        draw_lines(bg, BOX["day_big"], [day], f_day_big, HEADER_COLOR, align="center", line_spacing=0)

    # Draw month info in top-right - separate Chinese and English
    month_cn = (row.get("month_cn","") or "").strip()
    if month_cn:
        draw_lines(bg, BOX["month_cn"], as_lines(month_cn), f_month_cn, HEADER_COLOR, align="right")
    
    month_en = (row.get("month_en","") or "").strip()
    if month_en:
        draw_lines(bg, BOX["month_en"], as_lines(month_en), f_month_en, HEADER_COLOR, align="right")

    # Draw weekday
    weekday_en = (row.get('weekday_en','') or '').strip()
    weekday_cn = (row.get('weekday_cn','') or '').strip()
    weekday_line = weekday_cn if weekday_cn else weekday_en
    if weekday_line:
        draw_lines(bg, BOX["weekday"], as_lines(weekday_line), f_small_cn, HEADER_COLOR, align="right")

    # Draw lunar date
    lunar = (row.get("lunar","") or "").strip()
    solar = (row.get("solar_term","") or "").strip()
    lunar_line = f"农历 {lunar}" if lunar else ""
    if solar:
        lunar_line = f"{lunar_line} · {solar}" if lunar_line else solar
    if lunar_line:
        draw_lines(bg, BOX["lunar"], as_lines(lunar_line), f_small_cn, HEADER_COLOR, align="right")

    # Main long text: wrap + auto-fit
    x, y, w, h = BOX["main_text"]
    main_text = (row.get("main_text","") or "").strip()
    
    # Determine if text is primarily Chinese or English
    chinese_chars = sum(1 for c in main_text if '\u4e00' <= c <= '\u9fff')
    is_chinese = chinese_chars > len(main_text) * 0.3
    
    font_path = font_cn if is_chinese else font_en
    font_index = font_index_cn if is_chinese else font_index_en
    
    main_font, main_lines = fit_text_in_box(
        draw, main_text, font_path=font_path, font_index=font_index,
        box_w=w, box_h=h,
        start_size=72, min_size=42,  # Larger for better readability
        line_spacing=40  # More spacing for better readability
    )
    draw_lines(bg, BOX["main_text"], main_lines, main_font, TEXT, align="left", line_spacing=40)

    footer = (row.get("footer","") or "").strip()
    if footer:
        f_footer = load_font(font_cn, 40, font_index_cn)
        draw_lines(bg, BOX["footer"], [footer], f_footer, HEADER_COLOR, align="center", line_spacing=10)

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