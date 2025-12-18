#!/opt/homebrew/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  img_text_audio_to_video_wrap.sh \
    -i <image> -a <audio> -o <output.mp4> -t <textfile> \
    [--x <px>] [--y <px>] [--w <px>] [--h <px>] \
    [--fontsize <n>] [--fontcolor <RRGGBB>] \
    [--boxcolor <RRGGBB@alpha>] [--outline <px>] \
    [--fontfile <path.ttf>] \
    [--fps <n>] [--crf <n>] [--preset <name>] \
    [--pad <0|1>] [--resolution <WxH>]

Notes:
  - Auto wrap is handled by ASS subtitle renderer (libass).
  - Text is read from a local file.
  - Text is centered inside the region; it wraps within region width (w).
  - Video duration follows audio via -shortest.
EOF
}

# Defaults
X=120
Y=120
W=800
H=240
FONTSIZE=54
FONTCOLOR="FFFFFF"       # ASS uses BBGGRR; we'll convert below
BOXCOLOR="000000@0.45"   # RRGGBB@alpha (0..1)
OUTLINE=2
FONTFILE=""
FPS=30
CRF=18
PRESET="medium"
PAD=1
RESOLUTION="1080x1920"

IMAGE=""
AUDIO=""
OUTPUT=""
TEXTFILE=""
TEXT_CONTENT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -i) IMAGE="$2"; shift 2;;
    -a) AUDIO="$2"; shift 2;;
    -o) OUTPUT="$2"; shift 2;;
    -t) TEXTFILE="$2"; shift 2;;
    --x) X="$2"; shift 2;;
    --y) Y="$2"; shift 2;;
    --w) W="$2"; shift 2;;
    --h) H="$2"; shift 2;;
    --fontsize) FONTSIZE="$2"; shift 2;;
    --fontcolor) FONTCOLOR="$2"; shift 2;;
    --boxcolor) BOXCOLOR="$2"; shift 2;;
    --outline) OUTLINE="$2"; shift 2;;
    --fontfile) FONTFILE="$2"; shift 2;;
    --fps) FPS="$2"; shift 2;;
    --crf) CRF="$2"; shift 2;;
    --preset) PRESET="$2"; shift 2;;
    --pad) PAD="$2"; shift 2;;
    --resolution) RESOLUTION="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 1;;
  esac
done

if [[ -z "$IMAGE" || -z "$AUDIO" || -z "$OUTPUT" || -z "$TEXTFILE" ]]; then
  echo "Missing required args."
  usage
  exit 1
fi

if [[ ! -f "$TEXTFILE" ]]; then
  echo "Text file not found: $TEXTFILE"
  exit 1
fi

command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg not found."; exit 1; }

# Parse resolution
RES_W="${RESOLUTION%x*}"
RES_H="${RESOLUTION#*x}"

# Region center
CX=$(( X + W / 2 ))
CY=$(( Y + H / 2 ))

# Convert RRGGBB -> ASS BBGGRR
rrggbb_to_ass_bbggrr() {
  local c
  c="$(printf "%s" "$1" | tr '[:lower:]' '[:upper:]')"
  local rr="${c:0:2}" gg="${c:2:2}" bb="${c:4:2}"
  echo "${bb}${gg}${rr}"
}

# BOXCOLOR format: RRGGBB@alpha
BOX_RGB="${BOXCOLOR%@*}"
BOX_A="${BOXCOLOR#*@}"  # 0..1
if [[ "$BOX_RGB" == "$BOXCOLOR" ]]; then
  BOX_A="0.45"
fi

# ASS alpha: 00 opaque .. FF transparent
alpha_to_ass() {
  python3 - <<PY
a=float("$1")
a=max(0.0,min(1.0,a))
# user alpha means opacity; ASS uses transparency
t=round(255*(1.0-a))
print(f"{t:02X}")
PY
}

ASS_TEXT_COLOR="$(rrggbb_to_ass_bbggrr "$FONTCOLOR")"
ASS_BOX_COLOR="$(rrggbb_to_ass_bbggrr "$BOX_RGB")"
ASS_BOX_ALPHA="$(alpha_to_ass "$BOX_A")"

TEXT_CONTENT="$(cat "$TEXTFILE")"

# Escape text for ASS (escape \ { } and convert newlines)
# ASS uses \N for explicit line breaks; we leave wrapping to ASS, but keep user newlines.
ESC_TEXT="$(printf "%s" "$TEXT_CONTENT" \
  | sed -e 's/\\/\\\\/g' -e 's/{/\\{/g' -e 's/}/\\}/g' \
  | awk '{printf "%s\\N", $0}' | sed 's/\\N$//')"

# Temp ASS file
ASS_FILE="$(mktemp -t overlay.XXXXXX.ass)"

# If a fontfile is provided, we can still reference font name via "Fontname",
# but libass doesn't accept fontfile path directly in the ASS style.
# In practice: install font system-wide or pick a common Fontname.
# We'll set Fontname to "Arial" by default; macOS will resolve it.
FONTNAME="Arial"

cat > "$ASS_FILE" <<EOF
[Script Info]
ScriptType: v4.00+
PlayResX: $RES_W
PlayResY: $RES_H
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Txt,$FONTNAME,$FONTSIZE,&H00${ASS_TEXT_COLOR},&H00000000,&H00000000,&H${ASS_BOX_ALPHA}${ASS_BOX_COLOR},0,0,0,0,100,100,0,0,3,$OUTLINE,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,9:59:59.00,Txt,,0,0,0,,{\\an5\\pos($CX,$CY)\\clip($X,$Y,$((X+W)),$((Y+H)))\\q2}$ESC_TEXT
EOF

# Scaling / padding (FFmpeg filters want W:H, not WxH)
if [[ "$PAD" == "1" ]]; then
  SCALE_PAD_FILTER="scale=${RES_W}:${RES_H}:force_original_aspect_ratio=decrease,pad=${RES_W}:${RES_H}:(ow-iw)/2:(oh-ih)/2"
else
  SCALE_PAD_FILTER="scale=${RES_W}:${RES_H}"
fi

# Render
ffmpeg -y \
  -loop 1 -i "$IMAGE" \
  -i "$AUDIO" \
  -vf "${SCALE_PAD_FILTER},subtitles='${ASS_FILE}'" \
  -map 0:v -map 1:a \
  -r "$FPS" \
  -c:v libx264 -preset "$PRESET" -crf "$CRF" -tune stillimage \
  -c:a aac -b:a 128k \
  -shortest \
  -pix_fmt yuv420p \
  "$OUTPUT"

rm -f "$ASS_FILE"
echo "Done: $OUTPUT"
