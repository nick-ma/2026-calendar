#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import os
import re
import subprocess
import tempfile
from pathlib import Path
import openai

# OpenAI TTS input max length (chars) per request
MAX_CHARS = 4096  #  [oai_citation:2‡OpenAI Platform](https://platform.openai.com/docs/api-reference/audio/createSpeech?utm_source=chatgpt.com)

def run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stdout)

def smart_split_text(text: str, limit: int = MAX_CHARS):
    """
    Split text into chunks <= limit, preferring paragraph/sentence boundaries.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return [text]

    # split by double newlines first
    parts = re.split(r"\n{2,}", text)
    chunks = []
    cur = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) > limit:
            # fallback: sentence split
            sentences = re.split(r"(?<=[。！？.!?])\s*", part)
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if len(s) > limit:
                    # hard cut
                    for i in range(0, len(s), limit):
                        chunks.append(s[i:i+limit])
                    continue
                if not cur:
                    cur = s
                elif len(cur) + 1 + len(s) <= limit:
                    cur = cur + " " + s
                else:
                    chunks.append(cur)
                    cur = s
            continue

        if not cur:
            cur = part
        elif len(cur) + 2 + len(part) <= limit:
            cur = cur + "\n\n" + part
        else:
            chunks.append(cur)
            cur = part

    if cur:
        chunks.append(cur)

    return chunks

def tts_to_file(text: str, out_path: Path, model: str, voice: str, fmt: str, speed: float, instructions: str | None):
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Streaming API example is documented by OpenAI  [oai_citation:3‡OpenAI Platform](https://platform.openai.com/docs/api-reference/audio/speech-audio-delta-event?_clear=true&adobe_mc=MCMID%3D12000814905405683995335849378418609464%7CMCORGID%3DA8833BC75245AF9E0A490D4D%2540AdobeOrg%7CTS%3D1744156800&lang=python)
    kwargs = dict(model=model, voice=voice, input=text, response_format=fmt, speed=speed)
    if instructions:
        kwargs["instructions"] = instructions

    with openai.audio.speech.with_streaming_response.create(**kwargs) as resp:
        resp.stream_to_file(out_path)

def concat_audio_ffmpeg(inputs: list[Path], out_path: Path):
    """
    Concatenate audio segments (same codec/format) using ffmpeg concat demuxer.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        lst = td / "list.txt"
        lines = [f"file '{p.as_posix()}'" for p in inputs]
        lst.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(lst),
            "-c", "copy",
            str(out_path),
        ]
        run(cmd)

def gen_one(text: str, out_file: Path, model: str, voice: str, fmt: str, speed: float,
            instructions: str | None, allow_split_concat: bool):
    if not allow_split_concat or len(text) <= MAX_CHARS:
        tts_to_file(text, out_file, model, voice, fmt, speed, instructions)
        return

    chunks = smart_split_text(text, MAX_CHARS)
    segs = []
    for idx, chunk in enumerate(chunks, 1):
        seg_path = out_file.parent / f"{out_file.stem}.part{idx:02d}.{fmt}"
        tts_to_file(chunk, seg_path, model, voice, fmt, speed, instructions)
        segs.append(seg_path)

    concat_audio_ffmpeg(segs, out_file)

def load_text_from_args(args) -> str:
    if args.text:
        return args.text
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8")
    raise ValueError("Provide --text or --text-file, or use --csv mode.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-4o-mini-tts",
                    help="tts-1 | tts-1-hd | gpt-4o-mini-tts")  #  [oai_citation:4‡OpenAI Platform](https://platform.openai.com/docs/api-reference/audio/createSpeech?utm_source=chatgpt.com)
    ap.add_argument("--voice", default="alloy",
                    help="alloy, ash, ballad, coral, echo, fable, onyx, nova, sage, shimmer, verse")  #  [oai_citation:5‡OpenAI Platform](https://platform.openai.com/docs/api-reference/audio/createSpeech?utm_source=chatgpt.com)
    ap.add_argument("--format", default="wav",
                    help="mp3|opus|aac|flac|wav|pcm")  #  [oai_citation:6‡OpenAI Platform](https://platform.openai.com/docs/api-reference/audio/createSpeech?utm_source=chatgpt.com)
    ap.add_argument("--speed", type=float, default=1.0,
                    help="0.25 - 4.0")  #  [oai_citation:7‡OpenAI Platform](https://platform.openai.com/docs/api-reference/audio/createSpeech?utm_source=chatgpt.com)
    ap.add_argument("--instructions", default=None,
                    help="Extra voice instructions (works with gpt-4o-mini-tts, not tts-1/tts-1-hd).")  #  [oai_citation:8‡OpenAI Platform](https://platform.openai.com/docs/api-reference/audio/createSpeech?utm_source=chatgpt.com)
    ap.add_argument("--split-concat", action="store_true",
                    help="If text > 4096 chars, split + concat with ffmpeg.")  #  [oai_citation:9‡OpenAI Platform](https://platform.openai.com/docs/api-reference/audio/createSpeech?utm_source=chatgpt.com)

    # single-text mode
    ap.add_argument("--text", default=None)
    ap.add_argument("--text-file", default=None)
    ap.add_argument("--out", default=None, help="output audio file path")

    # CSV batch mode
    ap.add_argument("--csv", default=None)
    ap.add_argument("--text-col", default="main_text")
    ap.add_argument("--date-col", default="date")
    ap.add_argument("--audio-out-dir", default=None)

    args = ap.parse_args()

    if args.csv:
        if not args.audio_out_dir:
            raise ValueError("--audio-out-dir is required in --csv mode")
        out_dir = Path(args.audio_out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        with open(args.csv, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

        for i, row in enumerate(rows, 1):
            date = (row.get(args.date_col) or "").strip()
            text = (row.get(args.text_col) or "").strip()
            if not date:
                raise ValueError(f"Row {i}: missing {args.date_col}")
            if not text:
                print(f"[{i}/{len(rows)}] {date}: empty text, skipped")
                continue

            out_file = out_dir / f"{date}.{args.format}"
            print(f"[{i}/{len(rows)}] {date} -> {out_file.name}")
            gen_one(text, out_file, args.model, args.voice, args.format, args.speed, args.instructions, args.split_concat)
        print("Done.")
        return

    # single mode
    text = load_text_from_args(args)
    if not args.out:
        raise ValueError("--out is required in single mode")
    out_file = Path(args.out)
    gen_one(text, out_file, args.model, args.voice, args.format, args.speed, args.instructions, args.split_concat)
    print("Done.")

if __name__ == "__main__":
    main()