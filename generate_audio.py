#!/usr/bin/env python3
"""Build a language-learning listening track from sentence pairs, using Edge TTS.

Each pair in the input file is keyed by language code, e.g. {"ro": "...",
"en": "..."} or {"en": "...", "uk": "..."}. --learning-lang picks which of
the two languages is the one you're learning: its sentence is spoken
(optionally repeated at different speeds) first, then the other language's
sentence is spoken once as the translation.

Usage:
    python generate_audio.py --input sentences.example.json --learning-lang ro
    python generate_audio.py --input sentences.example.en-uk.json --learning-lang en --target-speeds 0.7 0.85 1.0
"""

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import zipfile

from pydub import AudioSegment

from tts_engines import LANG_VOICES, synthesize


def load_pairs(path: str):
    if path.endswith(".csv"):
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = [row for row in reader if row and row[0].strip()]
        if len(rows) < 2:
            sys.exit("CSV file needs a header row (language codes) plus at least one data row.")
        header = [h.strip() for h in rows[0]]
        if len(header) != 2:
            sys.exit(f"CSV header must have exactly 2 columns (language codes), got {header!r}.")
        return header, [dict(zip(header, (cell.strip() for cell in row))) for row in rows[1:]]

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not data:
        return [], []
    langs = list(data[0].keys())
    if len(langs) != 2:
        sys.exit(f"Each JSON entry must have exactly 2 language keys, got {langs!r}.")
    return langs, data


def parse_voice_overrides(pairs):
    overrides = {}
    for item in pairs or []:
        if "=" not in item:
            sys.exit(f"--voice expects LANG=VOICE_ID, got {item!r}")
        lang, voice = item.split("=", 1)
        overrides[lang.strip()] = voice.strip()
    return overrides


def resolve_voice(lang_code, overrides):
    if lang_code in overrides:
        return overrides[lang_code]
    if lang_code not in LANG_VOICES:
        sys.exit(f"No default voice for language {lang_code!r}. "
                  f"Known languages: {', '.join(sorted(LANG_VOICES))}. "
                  f"Pass one explicitly with --voice {lang_code}=<voice-id> (see `edge-tts --list-voices`).")
    return LANG_VOICES[lang_code]


def build_track(pairs, learning_lang, translation_lang, learning_voice, translation_voice,
                 learning_speeds, pause_after_learning_ms, pause_after_translation_ms,
                 include_translation, workdir):
    track = AudioSegment.silent(duration=0)
    for i, pair in enumerate(pairs, 1):
        print(f"[{i}/{len(pairs)}] {pair[learning_lang]!r}", file=sys.stderr)

        clip_by_speed = {}
        for rep, speed in enumerate(learning_speeds, 1):
            if speed not in clip_by_speed:
                learning_path = os.path.join(workdir, f"{i:03d}_learning_{rep}.mp3")
                synthesize(pair[learning_lang], learning_voice, speed, learning_path)
                clip_by_speed[speed] = AudioSegment.from_file(learning_path)
            track += clip_by_speed[speed]
            track += AudioSegment.silent(duration=pause_after_learning_ms)

        if include_translation and pair.get(translation_lang):
            translation_path = os.path.join(workdir, f"{i:03d}_translation.mp3")
            synthesize(pair[translation_lang], translation_voice, 1.0, translation_path)
            track += AudioSegment.from_file(translation_path)
            track += AudioSegment.silent(duration=pause_after_translation_ms)

    return track


def _slugify(text, max_len=40):
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_')
    return slug[:max_len] or 'pair'


def _slice_pairs(spec, pairs):
    """Return a subset of pairs according to a range spec.

    Formats (1-based, inclusive):
      N      first N rows   e.g. "10"
      M:N    rows M to N    e.g. "2:5"
      -N     last N rows    e.g. "-2"
    """
    if not spec or not str(spec).strip():
        return pairs
    spec = str(spec).strip()
    try:
        if spec.startswith('-') and spec[1:].isdigit():
            n = int(spec[1:])
            return pairs[-n:] if n else []
        if ':' in spec:
            left, _, right = spec.partition(':')
            start = (int(left) - 1) if left.strip() else 0
            end = int(right) if right.strip() else len(pairs)
            return pairs[max(0, start):end]
        n = int(spec)
        return pairs[:n]
    except (ValueError, IndexError):
        raise ValueError(
            f"Invalid row range {spec!r}. "
            "Use N (first N), M:N (rows M to N, 1-based inclusive), or -N (last N)."
        )


def build_split_tracks(pairs, learning_lang, translation_lang, learning_voice, translation_voice,
                       learning_speeds, pause_after_learning_ms, pause_after_translation_ms,
                       include_translation, workdir, output_dir):
    """Export one MP3 per pair into output_dir; return list of written paths."""
    paths = []
    for i, pair in enumerate(pairs, 1):
        print(f"[{i}/{len(pairs)}] (split) {pair[learning_lang]!r}", file=sys.stderr)
        segment = AudioSegment.silent(duration=0)
        clip_by_speed = {}
        for rep, speed in enumerate(learning_speeds, 1):
            if speed not in clip_by_speed:
                p = os.path.join(workdir, f"p{i:03d}_s{rep}.mp3")
                synthesize(pair[learning_lang], learning_voice, speed, p)
                clip_by_speed[speed] = AudioSegment.from_file(p)
            segment += clip_by_speed[speed]
            segment += AudioSegment.silent(duration=pause_after_learning_ms)
        if include_translation and pair.get(translation_lang):
            p = os.path.join(workdir, f"p{i:03d}_t.mp3")
            synthesize(pair[translation_lang], translation_voice, 1.0, p)
            segment += AudioSegment.from_file(p)
            segment += AudioSegment.silent(duration=pause_after_translation_ms)
        out = os.path.join(output_dir, f"{i:03d}_{_slugify(pair[learning_lang])}.mp3")
        segment.export(out, format="mp3")
        paths.append(out)
    return paths


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="JSON or CSV file of sentence pairs")
    parser.add_argument("--output", default=None,
                         help="Output audio file path (default: same path/name as --input, with a .mp3 extension)")
    parser.add_argument("--learning-lang", required=True,
                         help="Language code (matching a key in --input) that you're learning. "
                              "This sentence goes first and gets repeated/sped up; the other "
                              "language in the file is treated as the translation.")
    parser.add_argument("--voice", action="append", metavar="LANG=VOICE_ID",
                         help="Override the default voice for a language, e.g. --voice uk=uk-UA-OstapNeural. "
                              "Repeatable. See `edge-tts --list-voices`.")
    parser.add_argument("--target-speeds", type=float, nargs="+", default=[0.85],
                         help="Speed multiplier for each repetition of the learning-language sentence, in "
                              "order (1.0 = normal, 0.8 = 20%% slower). One value per repeat, e.g. "
                              "--target-speeds 0.7 0.85 1.0 says it 3 times, slow to normal.")
    parser.add_argument("--pause-after-target", type=float, default=1.0,
                         help="Seconds of silence after each learning-language repetition")
    parser.add_argument("--pause-after-translation", type=float, default=1.5,
                         help="Seconds of silence after the translation, before the next pair")
    parser.add_argument("--no-translation", action="store_true",
                         help="Skip the translation audio entirely (learning language only)")
    parser.add_argument("--split", action="store_true",
                         help="Write one MP3 per sentence pair and collect them in a ZIP archive "
                              "(default output path changes from .mp3 to .zip)")
    parser.add_argument("--rows", default=None, metavar="RANGE",
                         help="Subset of pairs to process. "
                              "N = first N, M:N = rows M to N (1-based inclusive), -N = last N. "
                              "Examples: --rows 10  --rows 2:5  --rows -2")
    args = parser.parse_args()

    if args.split:
        zip_path = args.output or os.path.splitext(args.input)[0] + ".zip"
    else:
        output_path = args.output or os.path.splitext(args.input)[0] + ".mp3"

    langs, pairs = load_pairs(args.input)
    if not pairs:
        sys.exit("No sentence pairs found in input file.")
    if args.learning_lang not in langs:
        sys.exit(f"--learning-lang {args.learning_lang!r} not found in input file's languages {langs!r}.")

    if args.rows:
        try:
            pairs = _slice_pairs(args.rows, pairs)
        except ValueError as e:
            sys.exit(str(e))
        if not pairs:
            sys.exit(f"--rows {args.rows!r} selected 0 rows from a {len(load_pairs(args.input)[1])}-row file.")
    translation_lang = next(l for l in langs if l != args.learning_lang)

    overrides = parse_voice_overrides(args.voice)
    learning_voice = resolve_voice(args.learning_lang, overrides)
    translation_voice = resolve_voice(translation_lang, overrides)

    with tempfile.TemporaryDirectory() as workdir:
        if args.split:
            output_dir = tempfile.mkdtemp()
            try:
                build_split_tracks(
                    pairs, args.learning_lang, translation_lang, learning_voice, translation_voice,
                    args.target_speeds,
                    int(args.pause_after_target * 1000),
                    int(args.pause_after_translation * 1000),
                    not args.no_translation,
                    workdir,
                    output_dir,
                )
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fname in sorted(f for f in os.listdir(output_dir) if f.endswith(".mp3")):
                        zf.write(os.path.join(output_dir, fname), fname)
            finally:
                import shutil
                shutil.rmtree(output_dir, ignore_errors=True)
            print(f"Wrote {zip_path} ({len(pairs)} files, learning={args.learning_lang}, "
                  f"translation={translation_lang}, target_speeds={args.target_speeds})")
        else:
            track = build_track(
                pairs, args.learning_lang, translation_lang, learning_voice, translation_voice,
                args.target_speeds,
                int(args.pause_after_target * 1000),
                int(args.pause_after_translation * 1000),
                not args.no_translation,
                workdir,
            )
            track.export(output_path, format="mp3")
            print(f"Wrote {output_path} ({len(pairs)} pairs, learning={args.learning_lang}, "
                  f"translation={translation_lang}, target_speeds={args.target_speeds})")


if __name__ == "__main__":
    main()
