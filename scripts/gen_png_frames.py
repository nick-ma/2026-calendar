#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import re
from pathlib import Path
from typing import Dict, Any, Tuple
from PIL import Image, ImageDraw, ImageFont
import yaml

def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config

def get_color(config: Dict[str, Any], color_name: str) -> Tuple[int, int, int]:
    """Get color tuple from config by name."""
    colors = config.get('colors', {})
    color = colors.get(color_name, [255, 255, 255])
    return tuple(color[:3])  # Ensure RGB tuple

def get_box(config: Dict[str, Any], field_name: str) -> Tuple[int, int, int, int]:
    """Get layout box tuple (x, y, w, h) from config."""
    layout = config.get('layout', {})
    field_layout = layout.get(field_name, {})
    box = field_layout.get('box', [0, 0, 0, 0])
    return tuple(box[:4])

def get_field_config(config: Dict[str, Any], field_name: str) -> Dict[str, Any]:
    """Get field-specific configuration."""
    fields = config.get('fields', {})
    return fields.get(field_name, {})

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

    # Calculate total height of all lines
    total_text_h = len(lines) * line_h
    
    # For vertical centering: only if text fits in box and we have content
    if len(lines) > 0 and total_text_h < h and line_h <= h:
        yy = y + (h - total_text_h) // 2
    else:
        yy = y

    for line in lines:
        if not line.strip():  # Skip empty lines
            continue
        # Ensure yy is within box bounds
        if yy < y:
            yy = y
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
        draw.text((xx, yy), line, font=font, fill=fill)
        yy += line_h

def render_one(row: dict, bg_path: str, config: Dict[str, Any]) -> Image.Image:
    """Render a single calendar frame based on row data and configuration."""
    # Get canvas dimensions
    canvas = config.get('canvas', {})
    W = canvas.get('width', 1440)
    H = canvas.get('height', 2560)
    
    # Get font paths and indices
    fonts_config = config.get('fonts', {})
    font_cn = fonts_config.get('chinese', {}).get('path', '')
    font_en = fonts_config.get('english', {}).get('path', '')
    font_index_cn = fonts_config.get('chinese', {}).get('index', 0)
    font_index_en = fonts_config.get('english', {}).get('index', 0)
    
    if not font_cn or not font_en:
        raise ValueError("Font paths must be set in config or via command line")
    
    bg = Image.open(bg_path).convert("RGB").resize((W, H))
    draw = ImageDraw.Draw(bg)

    def as_lines(s): return [str(s or "").strip()]
    
    def get_font(field_name: str, font_type_override: str = None):
        """Get font for a field based on configuration."""
        field_config = get_field_config(config, field_name)
        font_config = field_config.get('font', {})
        font_type = font_type_override or font_config.get('type', 'english')
        font_size = font_config.get('size', 40)
        
        if font_type == 'chinese':
            return load_font(font_cn, font_size, font_index_cn)
        elif font_type == 'english':
            return load_font(font_en, font_size, font_index_en)
        else:
            # Default to english
            return load_font(font_en, font_size, font_index_en)

    # Draw large day number in top-left
    day = str(row.get("day","") or "").strip()
    if day:
        field_config = get_field_config(config, 'day_big')
        box = get_box(config, 'day_big')
        color = get_color(config, field_config.get('color', 'header'))
        align = field_config.get('align', 'center')
        line_spacing = field_config.get('line_spacing', 0)
        font = get_font('day_big')
        draw_lines(bg, box, [day], font, color, align=align, line_spacing=line_spacing)

    # Draw month info in top-right - separate Chinese and English
    month_cn = (row.get("month_cn","") or "").strip()
    if month_cn:
        field_config = get_field_config(config, 'month_cn')
        box = get_box(config, 'month_cn')
        color = get_color(config, field_config.get('color', 'header'))
        align = field_config.get('align', 'right')
        line_spacing = field_config.get('line_spacing', 10)
        font = get_font('month_cn')
        draw_lines(bg, box, as_lines(month_cn), font, color, align=align, line_spacing=line_spacing)
    
    month_en = (row.get("month_en","") or "").strip()
    if month_en:
        field_config = get_field_config(config, 'month_en')
        box = get_box(config, 'month_en')
        color = get_color(config, field_config.get('color', 'header'))
        align = field_config.get('align', 'right')
        line_spacing = field_config.get('line_spacing', 10)
        font = get_font('month_en')
        draw_lines(bg, box, as_lines(month_en), font, color, align=align, line_spacing=line_spacing)

    # Draw weekday
    weekday_en = (row.get('weekday_en','') or '').strip()
    weekday_cn = (row.get('weekday_cn','') or '').strip()
    weekday_line = weekday_cn if weekday_cn else weekday_en
    if weekday_line:
        field_config = get_field_config(config, 'weekday')
        box = get_box(config, 'weekday')
        color = get_color(config, field_config.get('color', 'header'))
        align = field_config.get('align', 'right')
        line_spacing = field_config.get('line_spacing', 10)
        font = get_font('weekday')
        draw_lines(bg, box, as_lines(weekday_line), font, color, align=align, line_spacing=line_spacing)

    # Draw lunar date
    lunar = (row.get("lunar","") or "").strip()
    solar = (row.get("solar_term","") or "").strip()
    lunar_line = f"农历 {lunar}" if lunar else ""
    if solar:
        lunar_line = f"{lunar_line} · {solar}" if lunar_line else solar
    if lunar_line:
        field_config = get_field_config(config, 'lunar')
        box = get_box(config, 'lunar')
        color = get_color(config, field_config.get('color', 'header'))
        align = field_config.get('align', 'right')
        line_spacing = field_config.get('line_spacing', 10)
        font = get_font('lunar')
        draw_lines(bg, box, as_lines(lunar_line), font, color, align=align, line_spacing=line_spacing)

    # Draw year in center-top
    date_str = (row.get("date","") or "").strip()
    if date_str:
        # Extract year from date string (format: YYYY-MM-DD)
        try:
            year = date_str.split("-")[0]
            if year and len(year) == 4:
                field_config = get_field_config(config, 'year')
                box = get_box(config, 'year')
                color = get_color(config, field_config.get('color', 'header'))
                align = field_config.get('align', 'center')
                line_spacing = field_config.get('line_spacing', 0)
                font = get_font('year')
                year_lines = as_lines(year)
                draw_lines(bg, box, year_lines, font, color, align=align, line_spacing=line_spacing)
        except (IndexError, ValueError):
            pass

    # Main long text: wrap + auto-fit
    box = get_box(config, 'main_text')
    _, _, w, h = box
    main_text = (row.get("main_text","") or "").strip()
    
    field_config = get_field_config(config, 'main_text')
    font_config = field_config.get('font', {})
    
    # Determine if text is primarily Chinese or English
    chinese_chars = sum(1 for c in main_text if '\u4e00' <= c <= '\u9fff')
    is_chinese = chinese_chars > len(main_text) * 0.3
    
    font_type = font_config.get('type', 'auto')
    if font_type == 'auto':
        font_path = font_cn if is_chinese else font_en
        font_index = font_index_cn if is_chinese else font_index_en
    elif font_type == 'chinese':
        font_path = font_cn
        font_index = font_index_cn
    else:
        font_path = font_en
        font_index = font_index_en
    
    start_size = font_config.get('size', 72)
    min_size = font_config.get('min_size', 42)
    line_spacing = field_config.get('line_spacing', 40)
    color = get_color(config, field_config.get('color', 'text'))
    align = field_config.get('align', 'left')
    
    main_font, main_lines = fit_text_in_box(
        draw, main_text, font_path=font_path, font_index=font_index,
        box_w=w, box_h=h,
        start_size=start_size, min_size=min_size,
        line_spacing=line_spacing
    )
    draw_lines(bg, box, main_lines, main_font, color, align=align, line_spacing=line_spacing)

    footer = (row.get("footer","") or "").strip()
    if footer:
        field_config = get_field_config(config, 'footer')
        box = get_box(config, 'footer')
        color = get_color(config, field_config.get('color', 'header'))
        align = field_config.get('align', 'center')
        line_spacing = field_config.get('line_spacing', 10)
        font = get_font('footer')
        draw_lines(bg, box, [footer], font, color, align=align, line_spacing=line_spacing)

    return bg

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Input CSV file with calendar data")
    ap.add_argument("--bg", required=True, help="Paper texture background png/jpg")
    ap.add_argument("--out", required=True, help="Output frames directory")
    ap.add_argument("--config", required=True, help="YAML configuration file")
    ap.add_argument("--font-cn", help="Chinese font .ttf/.ttc (overrides config)")
    ap.add_argument("--font-en", help="English font .ttf/.ttc (overrides config)")
    ap.add_argument("--font-index-cn", type=int, help="Chinese font index (overrides config)")
    ap.add_argument("--font-index-en", type=int, help="English font index (overrides config)")
    args = ap.parse_args()

    # Load configuration
    config = load_config(args.config)
    
    # Override font paths from command line if provided
    if args.font_cn:
        if 'fonts' not in config:
            config['fonts'] = {}
        if 'chinese' not in config['fonts']:
            config['fonts']['chinese'] = {}
        config['fonts']['chinese']['path'] = args.font_cn
    
    if args.font_en:
        if 'fonts' not in config:
            config['fonts'] = {}
        if 'english' not in config['fonts']:
            config['fonts']['english'] = {}
        config['fonts']['english']['path'] = args.font_en
    
    if args.font_index_cn is not None:
        if 'fonts' not in config:
            config['fonts'] = {}
        if 'chinese' not in config['fonts']:
            config['fonts']['chinese'] = {}
        config['fonts']['chinese']['index'] = args.font_index_cn
    
    if args.font_index_en is not None:
        if 'fonts' not in config:
            config['fonts'] = {}
        if 'english' not in config['fonts']:
            config['fonts']['english'] = {}
        config['fonts']['english']['index'] = args.font_index_en
    
    # Validate required font paths
    fonts_config = config.get('fonts', {})
    font_cn = fonts_config.get('chinese', {}).get('path', '')
    font_en = fonts_config.get('english', {}).get('path', '')
    
    if not font_cn:
        raise ValueError("Chinese font path must be set in config file or via --font-cn")
    if not font_en:
        raise ValueError("English font path must be set in config file or via --font-en")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.csv, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    for i, row in enumerate(rows, 1):
        date = (row.get("date") or "").strip()
        if not date:
            raise ValueError(f"Row {i} missing 'date'")
        img = render_one(row, args.bg, config)
        img.save(out_dir / f"{date}.png", "PNG")
        print(f"[{i}/{len(rows)}] {date}.png")

    print("Done.")

if __name__ == "__main__":
    main()