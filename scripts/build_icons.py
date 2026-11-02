"""Draw the app icons. Run this by hand from the project root and commit the result:
    python scripts/build_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUTPUT = Path(__file__).parent.parent / "app" / "icons"
BACKGROUND = (7, 9, 19)
SIZE = 1024

def draw_icon(content_scale):
    """A Sun, two orbits and a Voyager heading out. content_scale leaves room for masks."""
    image = Image.new("RGB", (SIZE, SIZE), BACKGROUND)
    scale = SIZE * content_scale
    center = SIZE / 2
    sun_x, sun_y = center - scale * 0.24, center + scale * 0.12

    glow = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    radius = scale * 0.13
    ImageDraw.Draw(glow).ellipse((sun_x - radius, sun_y - radius, sun_x + radius, sun_y + radius), fill=(255, 180, 80))
    glow = glow.filter(ImageFilter.GaussianBlur(scale * 0.06))
    image = Image.composite(glow, image, glow.convert("L"))

    draw = ImageDraw.Draw(image)
    line = max(3, round(scale * 0.012))
    for orbit in (0.2, 0.36):
        r = scale * orbit
        draw.ellipse((sun_x - r, sun_y - r, sun_x + r, sun_y + r), outline=(92, 104, 150), width=line)
    r = scale * 0.06
    draw.ellipse((sun_x - r, sun_y - r, sun_x + r, sun_y + r), fill=(255, 236, 190))

    craft_x, craft_y = center + scale * 0.34, center - scale * 0.3
    draw.line((sun_x, sun_y, craft_x, craft_y), fill=(244, 184, 96), width=round(scale * 0.024))
    r = scale * 0.05
    draw.ellipse((craft_x - r, craft_y - r, craft_x + r, craft_y + r), fill=(244, 184, 96))
    return image

def main():
    OUTPUT.mkdir(exist_ok=True)
    regular = draw_icon(0.9)
    # Android may crop this one into a circle, so keep everything well inside
    maskable = draw_icon(0.68)
    for name, image, size in [
        ("icon-192.png", regular, 192),
        ("icon-512.png", regular, 512),
        ("icon-maskable-512.png", maskable, 512),
        ("apple-touch-icon.png", maskable, 180),
        ("favicon-32.png", regular, 32),
    ]:
        path = OUTPUT / name
        image.resize((size, size), Image.LANCZOS).save(path, optimize=True)
        print(name, path.stat().st_size // 1024, "KB")

if __name__ == "__main__":
    main()
