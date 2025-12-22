# 2026 Calendar Assets

Toolkit for generating a 9:16 portrait 2026 calendar: render daily PNG frames from a CSV, synthesize narration with OpenAI TTS, and wrap an image + text + audio into short MP4 clips.

## Requirements
- Python 3.10+ with `openai` and `Pillow`
- `ffmpeg` available on `PATH`
- Fonts: one Chinese font (`--font-cn`) and one Latin font (`--font-en`)
- OpenAI API key in `OPENAI_API_KEY`

Install the Python deps (optional virtualenv recommended):
```bash
python -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install openai pillow
```

## Data input
Populate `data/calendar_2026.csv` with UTF-8 rows containing at least:
```
date,month_cn,month_en,lunar,solar_term,weekday_en,weekday_cn,day,main_text,footer
```
`date` is used as the filename stem (`2026-01-01` → `2026-01-01.png` / `.wav`). `main_text` is the long paragraph rendered in the center block.

## Generate PNG frames
```bash
python scripts/gen_png_frames.py \
  --csv data/calendar_2026.csv \
  --bg assets/bg01.jpg \
  --out out/frames_2026 \
  --font-cn fonts/Songti.ttc \
  --font-en fonts/Athelas.ttc
```
Adjust `BOX` coordinates in `scripts/gen_png_frames.py` if your template background differs.

## Text-to-speech audio
Single file:
```bash
python scripts/tts_openai.py \
  --text-file text.txt \
  --out audio/sample.wav \
  --voice ash --model gpt-4o-mini-tts
```
Batch from the CSV (one audio per row):
```bash
python scripts/tts_openai.py \
  --csv data/calendar_2026.csv \
  --audio-out-dir audio \
  --text-col main_text \
  --date-col date \
  --voice ash --model gpt-4o-mini-tts \
  --split-concat
```
`--split-concat` lets the script slice text over 4096 chars and stitch the pieces via `ffmpeg`.

## Wrap image + text + audio into MP4
Use the helper wrapper (text is read from a plain file; wrapping is handled by libass):
```bash
bash img_text_audio_to_video_wrap.sh \
  -i out/frames/2026-01-01.png \
  -a audio/2026-01-01.wav \
  -t txt/2026-01-01.txt \
  -o out/2026-01-01.mp4 \
  --resolution 1080x1920 --fontsize 54
```
Key options:
- `--x/--y/--w/--h`: text box region in pixels
- `--fontfile`: custom font for overlays (falls back to Arial)
- `--pad 1`: letterbox/pillarbox to keep aspect ratio

Outputs land in `audio/` and `out/` (both ignored by git).
