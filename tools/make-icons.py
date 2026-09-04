#!/usr/bin/env python3
"""
Turn the source logo into an installable icon set.

The source export (`logo.png`) is a non-square RGB image with the black
background baked in, which would render as a black rectangle in the dash. This
script keys that background out, squares the mark and writes the sizes
freedesktop expects.

Re-run it after re-exporting the logo:

    python3 tools/make-icons.py [source.png]
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO / "logo.png"
OUT_DIR = REPO / "src" / "unofficial_protonvpn" / "assets" / "icons"

SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
#: Fraction of the canvas left empty around the mark. Icons that bleed to the
#: very edge look oversized next to other icons in the dash.
MARGIN = 0.06
#: How close to black a pixel must be to count as background.
FUZZ = "20%"


def key_out_background(source: Path, dest: Path) -> None:
    """Flood-fill the black background to transparent, inward from each corner.

    Flood fill rather than a global colour key: the mark encloses a dark
    triangle of its own, and a global key would punch a hole through it.
    """
    with Image.open(source) as probe:
        width, height = probe.size

    corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    command = ["magick", str(source), "-alpha", "set", "-fuzz", FUZZ]
    for x, y in corners:
        command += ["-fill", "none", "-floodfill", f"+{x}+{y}", "black"]
    command.append(str(dest))

    subprocess.run(command, check=True)


def square(image: Image.Image) -> Image.Image:
    """Trim to the mark, then centre it on a transparent square canvas."""
    bbox = image.getbbox()
    if bbox is None:
        raise SystemExit("The source image is fully transparent - nothing to do.")
    mark = image.crop(bbox)

    side = int(max(mark.size) * (1 + 2 * MARGIN))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(
        mark,
        ((side - mark.width) // 2, (side - mark.height) // 2),
        mark,
    )
    return canvas


def desaturate(image: Image.Image) -> Image.Image:
    """A grey version of the mark, for the disconnected tray icon.

    The tray shows gold when the tunnel is up and grey when it is not, so the
    icon says at a glance whether you are protected.
    """
    from PIL import ImageEnhance

    grey = ImageEnhance.Color(image.convert("RGBA")).enhance(0.0)
    # Lift it slightly so it does not vanish against a dark panel.
    return ImageEnhance.Brightness(grey).enhance(1.15)


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.exists():
        raise SystemExit(f"No such file: {source}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    keyed = OUT_DIR / ".keyed.png"

    key_out_background(source, keyed)
    with Image.open(keyed) as image:
        canvas = square(image.convert("RGBA"))
    keyed.unlink(missing_ok=True)

    grey = desaturate(canvas)

    for size in SIZES:
        resized = canvas.resize((size, size), Image.LANCZOS)
        path = OUT_DIR / f"app-icon-{size}.png"
        resized.save(path, "PNG", optimize=True)
        print(f"  {path.relative_to(REPO)}")

        dimmed = grey.resize((size, size), Image.LANCZOS)
        grey_path = OUT_DIR / f"app-icon-disconnected-{size}.png"
        dimmed.save(grey_path, "PNG", optimize=True)
        print(f"  {grey_path.relative_to(REPO)}")

    canvas.save(OUT_DIR / "app-icon.png", "PNG", optimize=True)
    print(f"  {(OUT_DIR / 'app-icon.png').relative_to(REPO)} "
          f"({canvas.width}x{canvas.height} master)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
