"""Assemble the README's tour GIF from the PNG frames written by web/e2e/screenshots.spec.ts.

python scripts/make_tour_gif.py web/test-results/tour-frames docs/images/site-tour.gif
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

WIDTH = 960
FRAME_MS = 2200


def build(frames_dir: Path, output: Path) -> int:
    paths = sorted(frames_dir.glob("*.png"))
    if not paths:
        raise SystemExit(f"no PNG frames in {frames_dir}")
    frames: list[Image.Image] = []
    for path in paths:
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            height = round(rgb.height * WIDTH / rgb.width)
            resized = rgb.resize((WIDTH, height), Image.Resampling.LANCZOS)
            frames.append(resized.quantize(colors=128, method=Image.Quantize.MEDIANCUT))
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp.gif")
    frames[0].save(
        tmp, save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=0, optimize=True
    )
    tmp.replace(output)
    return len(frames)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    count = build(args.frames_dir, args.output)
    print(f"wrote {args.output} ({count} frames, {args.output.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
