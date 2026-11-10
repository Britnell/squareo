#!/usr/bin/env python3
"""Split the glyph paths in group "g426" of square-font.svg into one SVG per glyph.

Usage:
    python3 glyphs/split_glyphs.py [--src square-font.svg] [--out glyphs] [--group g426] [--dry-run]

How it works
------------
1. Finds the <g id="g426"> group in the SVG. Every direct child of it is one
glyph: a <path> child is a glyph by itself; a nested <g> child (e.g. "g425",
which holds the dot + the '?' shape together) is a glyph made of all its
paths. 28 children = 25 letters + '.', ',', '?' (one letter is missing from
the sheet). Transforms are ignored (Inkscape writes plain coordinates here).
2. Parses each glyph's path data (M L H V C S Q T A Z, absolute and relative).
3. Orders the glyphs in reading order (rows top -> bottom, left -> right),
names the letters A.. in order and the small low glyphs '.', ',', '?'.
4. Writes glyphs/<name>.svg - one glyph per file, outline geometry untouched,
   tight viewBox, fill-rule evenodd, no stroke.

Nothing in the source SVG is modified.
"""

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
PUNCT = ['.', ',', '?', '!', '-', "'", '"']
FILE_FOR = {'.': 'period', ',': 'comma', '?': 'question', '!': 'exclamation', '-': 'hyphen', "'": 'apostrophe', '"': 'quotedbl'}

NUM = r'-?\d*\.?\d+(?:[eE][-+]?\d+)?'
TOKEN = re.compile(r'[MmLlHhVvCcSsQqTtAaZz]|' + NUM)

# number of coordinates per command (after the command letter)
ARGC = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4, 'Q': 4, 'T': 2, 'A': 7, 'Z': 0}


# --------------------------------------------------------------------- parsing
def parse_path(d):
    """Parse path data into subpaths.

    Returns list of subpaths; each subpath is a list of commands:
        ('M', x, y)
        ('L', x, y) | ('H', y) | ('V', y)   -> normalised to ('L', x, y)
        ('C', x1, y1, x2, y2, x, y)
        ('S', x2, y2, x, y)
        ('Q', x1, y1, x, y)
        ('T', x, y)
        ('A', rx, ry, rot, large_arc, sweep, x, y)
    All coordinates absolute; the implicit closing segment is not added.
    Returns (subpaths, closed) where closed[k] is True if subpath k ends with Z.
    """
    toks = TOKEN.findall(d)
    i = 0
    subpaths, cur, closed = [], None, []
    cmd = None
    x = y = 0.0          # current point
    sx = sy = 0.0        # subpath start

    def take(n):
        nonlocal i
        vals = [float(toks[i + k]) for k in range(n)]
        i += n
        return vals

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd in 'Zz':
                if cur is not None:
                    subpaths.append(cur)
                    closed.append(True)
                    cur = None
                x, y = sx, sy
                continue
        elif cmd is None:
            raise ValueError('path data does not start with a command')

        upper, rel = cmd.upper(), cmd.islower()
        n = ARGC[upper]

        if upper == 'M':
            a = take(2)
            x, y = (x + a[0], y + a[1]) if rel else a
            if cur is not None:
                subpaths.append(cur)
            cur = [('M', x, y)]
            sx, sy = x, y
            cmd = 'l' if rel else 'L'      # extra pairs are implicit lineto
        elif upper in ('L', 'H', 'V'):
            a = take(n)
            if upper == 'L':
                x, y = (x + a[0], y + a[1]) if rel else a
            elif upper == 'H':
                x = x + a[0] if rel else a[0]
            else:
                y = y + a[0] if rel else a[0]
            cur.append(('L', x, y))
        elif upper == 'C':
            a = take(6)
            if rel:
                a = [a[0] + x, a[1] + y, a[2] + x, a[3] + y, a[4] + x, a[5] + y]
            cur.append(('C', *a))
            x, y = a[4], a[5]
        elif upper == 'S':
            a = take(4)
            if rel:
                a = [a[0] + x, a[1] + y, a[2] + x, a[3] + y]
            cur.append(('S', *a))
            x, y = a[2], a[3]
        elif upper == 'Q':
            a = take(4)
            if rel:
                a = [a[0] + x, a[1] + y, a[2] + x, a[3] + y]
            cur.append(('Q', *a))
            x, y = a[2], a[3]
        elif upper == 'T':
            a = take(2)
            x, y = (x + a[0], y + a[1]) if rel else a
            cur.append(('T', x, y))
        elif upper == 'A':
            a = take(7)
            if rel:
                a[5] += x
                a[6] += y
            cur.append(('A', a[0], a[1], a[2], int(a[3]), int(a[4]), a[5], a[6]))
            x, y = a[5], a[6]

    if cur is not None:
        subpaths.append(cur)
        closed.append(False)
    return subpaths, closed


def bbox(sub):
    """Bounding box of a subpath, including curve control points.

    Control points can extend past the curve, but these glyphs are boxy so
    this stays tight while never cutting off a curve.
    """
    xs, ys = [], []
    for c in sub:
        vals = [v for v in c[1:] if isinstance(v, float)]
        if c[0] == 'A':
            vals = vals[5:]          # only endpoint counts for arcs
        for k, v in enumerate(vals):
            (xs if k % 2 == 0 else ys).append(v)
    return (min(xs), min(ys), max(xs), max(ys))



# ------------------------------------------------------------------- grouping
def union_box(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def glyph_bboxes(glyphs):
    return [union_box([bbox(s) for s in g]) for g in glyphs]


PUNCT_ROW_Y = 205.0   # punctuation sits on its own last row below the letters


def names_for(cls):
    """Name glyphs: letters A.. in order, the small low ones are . , ? ! -
    (punctuation ordered left -> right, their y positions differ)."""
    punct = sorted((i for i, b in enumerate(cls) if b[1] > PUNCT_ROW_Y),
                   key=lambda i: cls[i][0])
    name_of = dict(zip(punct, PUNCT))
    if len(punct) != len(PUNCT):
        print('WARNING: expected %d punctuation glyphs below y=%s, found %d'
              % (len(PUNCT), PUNCT_ROW_Y, len(punct)), file=sys.stderr)
    letters = iter(LETTERS)
    return [name_of[i] if i in name_of else next(letters) for i in range(len(cls))]


def reading_order(glyphs, boxes):
    """Sort glyphs top->bottom, left->right (rows ~34 apart, glyph ~31 tall)."""
    items = sorted(range(len(glyphs)), key=lambda i: (round(boxes[i][1] / 20), boxes[i][0]))
    return items


# -------------------------------------------------------------------- writing
def fmt(v):
    s = '%.3f' % v
    s = s.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def subpath_to_d(sub):
    out = []
    for c in sub:
        kind = c[0]
        if kind == 'M':
            out.append('M %s %s' % (fmt(c[1]), fmt(c[2])))
        elif kind == 'L':
            out.append('L %s %s' % (fmt(c[1]), fmt(c[2])))
        elif kind == 'C':
            out.append('C ' + ' '.join(fmt(v) for v in c[1:]))
        elif kind == 'S':
            out.append('S ' + ' '.join(fmt(v) for v in c[1:]))
        elif kind == 'Q':
            out.append('Q ' + ' '.join(fmt(v) for v in c[1:]))
        elif kind == 'T':
            out.append('T %s %s' % (fmt(c[1]), fmt(c[2])))
        elif kind == 'A':
            out.append('A %s %s %s %d %d %s %s' % (fmt(c[1]), fmt(c[2]), fmt(c[3]),
                                                   c[4], c[5], fmt(c[6]), fmt(c[7])))
    return ' '.join(out) + ' Z'


def write_glyph(path, subpaths, box, pad=0.0):
    d = ' '.join(subpath_to_d(s) for s in subpaths)
    w = box[2] - box[0] + 2 * pad
    h = box[3] - box[1] + 2 * pad
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s" '
           'viewBox="%s %s %s %s"><path d="%s" fill="#000000" fill-rule="evenodd"/>'
           '</svg>\n' % (fmt(w), fmt(h), fmt(box[0] - pad), fmt(box[1] - pad),
                         fmt(w), fmt(h), d))
    with open(path, 'w') as fh:
        fh.write(svg)


# ----------------------------------------------------------------------- main
def collect_glyphs(root, group_id):
    """Each direct child of <g id="group_id"> is one glyph:
    a <path> child, or a nested <g> whose paths together form the glyph
    (e.g. g425 = '?' shape + dot). Returns a list of subpath-lists."""
    for g in root.iter('{http://www.w3.org/2000/svg}g'):
        if g.get('id') == group_id:
            glyphs = []
            for child in g:
                tag = child.tag.split('}')[-1]
                if tag == 'path' and child.get('d'):
                    subs, closed = parse_path(child.get('d'))
                    if not any(closed):
                        continue          # leftover stroked open line, not a glyph
                    glyphs.append(subs)
                elif tag == 'g':
                    subs = []
                    for p in child.iter('{http://www.w3.org/2000/svg}path'):
                        if p.get('d'):
                            s, _ = parse_path(p.get('d'))
                            subs.extend(s)
                    if subs:
                        glyphs.append(subs)
            if glyphs:
                return glyphs
    raise SystemExit('no glyphs found in <g id="%s">' % group_id)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_src = os.path.join(os.path.dirname(here), 'square-font.svg')

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--src', default=default_src, help='input svg (default: %(default)s)')
    ap.add_argument('--out', default=here, help='output folder (default: glyphs/)')
    ap.add_argument('--group', default='g426',
                    help='id of the group holding the glyphs (default: %(default)s)')
    ap.add_argument('--dry-run', action='store_true', help='only print what would be written')
    args = ap.parse_args()

    root = ET.parse(args.src).getroot()
    glyphs = collect_glyphs(root, args.group)
    boxes = glyph_bboxes(glyphs)
    ordered = reading_order(glyphs, boxes)

    cls = [boxes[i] for i in ordered]
    names = names_for(cls)
    print('group %s: %d glyphs' % (args.group, len(ordered)))
    if len(ordered) != len(LETTERS) + len(PUNCT):
        print('NOTE: found %d glyphs (a full sheet would have %d) - a letter is missing, '
              'names after the gap will be off by one'
              % (len(ordered), len(LETTERS) + len(PUNCT)), file=sys.stderr)

    if not args.dry_run:
        os.makedirs(args.out, exist_ok=True)

    letter_boxes = [b for b in cls if b[1] <= PUNCT_ROW_Y]
    if not letter_boxes:
        letter_boxes = cls
    size = max(max(b[2] - b[0] for b in letter_boxes),
               max(b[3] - b[1] for b in letter_boxes))
    baseline = max(b[3] for b in letter_boxes)   # bottom edge of the letters
    print('uniform bbox size: %s x %s' % (round(size, 2), round(size, 2)))

    for k, i in enumerate(ordered):
        name = names[k]
        fname = FILE_FOR.get(name, name) + '.svg'
        b = boxes[i]
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if name in ('.', ','):
            # period/comma: half-size square, bottom-aligned on the baseline
            half = size / 2
            uniform = (cx - half / 2, baseline - half, cx + half / 2, baseline)
        else:
            uniform = (cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)
        print('  %-9s %-12s bbox=%s subpaths=%d'
              % (name, fname, [round(v, 1) for v in boxes[i]], len(glyphs[i])))
        if not args.dry_run:
            write_glyph(os.path.join(args.out, fname), glyphs[i], uniform)

    if not args.dry_run:
        print('written to %s' % args.out)


if __name__ == '__main__':
    main()
