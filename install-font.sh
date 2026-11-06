#!/usr/bin/env bash
# Usage: ./install-font.sh font.ttf [more fonts...]
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
FF="${FONTFORGE:-$HOME/Applications/FontForge.AppImage}"
SRC="${SRC:-$here/square-font.svg}"

python3 "$here/split_glyphs.py" --src "$SRC" --out "$here"
"$FF" -lang=py -script "$here/build.pe"

# bake kern pairs into the TTF with fonttools feaLib (replaces any GPOS)
python3 - "$here/squareo.ttf" <<'PY'
import sys
from fontTools.ttLib import TTFont
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
path = sys.argv[1]
f = TTFont(path)
fea = '''languagesystem DFLT dflt;
feature kern {
    pos V A -622;
    pos V a -622;
    pos v A -622;
    pos v a -622;
} kern;
'''
addOpenTypeFeaturesFromString(f, fea)
f.save(path)
print("kern pairs compiled into", path)
PY

if [ $# -eq 0 ]; then
  set -- "$here/squareo.ttf"
fi

dest="${FONT_DIR:-$HOME/.local/share/fonts}"
mkdir -p "$dest"
for font in "$@"; do
  [ -f "$font" ] || { echo "Not found: $font" >&2; exit 1; }
  name="$(basename "$font")"
  rm -f "$dest/$name"
  install -m 644 "$font" "$dest/"
done

# copy into demo page
cp -f "$here/squareo.ttf" "$here/demo/public/squareo.ttf"

fc-cache -f "$dest"
echo "Installed to $dest"
