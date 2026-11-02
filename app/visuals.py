import io
import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

KM_PER_AU = 149597870.7

WIDTH, HEIGHT = 1120, 620
SCALE = 2  # Draw large and shrink, which smooths every edge
BACKGROUND = (7, 9, 19)
RING = (86, 96, 136)
LABEL = (178, 185, 212)
MUTED_CRAFT = (178, 185, 212)

SUN_X = 170  # The spacecraft fly off to the right of the Sun
PX_PER_SQRT_AU = 62

# Planet orbits in AU. Voyager 1 crossed the heliopause at about 122 AU, Voyager 2 at about 119.
ORBITS = [("Jupiter", 5.2), ("Saturn", 9.6), ("Uranus", 19.2), ("Neptune", 30.1)]
HELIOPAUSE_AU = 120

def _font(size):
    return ImageFont.load_default(size * SCALE)

def _radius(au):
    # A square-root scale keeps the planets visible beside the far-off spacecraft
    return math.sqrt(au) * PX_PER_SQRT_AU * SCALE

def _place(position):
    au = position["sun_km"] / KM_PER_AU
    longitude = math.atan2(position["sun_y_km"], position["sun_x_km"])
    return au, longitude

def _angle_between(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi

def _stars(draw, seed):
    rng = random.Random(seed)
    for _ in range(420):
        x, y = rng.randrange(WIDTH * SCALE), rng.randrange(HEIGHT * SCALE)
        size = rng.choice([1, 1, 1, 2, 2, 3])
        level = rng.randrange(60, 190)
        draw.ellipse((x, y, x + size, y + size), fill=(level, level, min(255, level + 25)))

def _sun(image, x, y):
    glow = Image.new("RGB", image.size, (0, 0, 0))
    draw = ImageDraw.Draw(glow)
    radius = 26 * SCALE
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 190, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(24 * SCALE))
    image.paste(Image.blend(image, Image.composite(glow, image, glow.convert("L")), 0.85))
    draw = ImageDraw.Draw(image)
    radius = 8 * SCALE
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 236, 190))

def _dashed_circle(draw, x, y, radius, color, width):
    steps = 180
    for i in range(0, steps, 2):
        start, end = 360 * i / steps, 360 * (i + 1) / steps
        draw.arc((x - radius, y - radius, x + radius, y + radius), start, end, fill=color, width=width)

def _craft(image, draw, sun_x, sun_y, angle, au, name, color, active):
    radius = _radius(au)
    x = sun_x + radius * math.cos(angle)
    y = sun_y - radius * math.sin(angle)

    # A straight line from the Sun, which is direction today rather than the route flown
    segments = 60
    for i in range(segments):
        if i % 2:
            continue
        t0, t1 = i / segments, (i + 1) / segments
        fade = 0.25 + 0.75 * t1
        line = tuple(int(BACKGROUND[c] + (color[c] - BACKGROUND[c]) * fade * (1 if active else 0.55)) for c in range(3))
        draw.line(
            (sun_x + (x - sun_x) * t0, sun_y + (y - sun_y) * t0,
             sun_x + (x - sun_x) * t1, sun_y + (y - sun_y) * t1),
            fill=line,
            width=(2 if active else 1) * SCALE,
        )

    if active:
        glow = Image.new("RGB", image.size, (0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        halo = 15 * SCALE
        glow_draw.ellipse((x - halo, y - halo, x + halo, y + halo), fill=color)
        glow = glow.filter(ImageFilter.GaussianBlur(12 * SCALE))
        image.paste(Image.blend(image, Image.composite(glow, image, glow.convert("L")), 0.9))
        draw = ImageDraw.Draw(image)

    dot = (10 if active else 7) * SCALE
    draw.ellipse((x - dot, y - dot, x + dot, y + dot), fill=color)

    title_font = _font(36 if active else 28)
    detail_font = _font(26 if active else 23)
    above = math.sin(angle) >= 0 if abs(math.sin(angle)) > 0.05 else active
    title_y = y - (84 if above else -16) * SCALE
    # Keep the label inside the picture, moving it beside the dot if it would run off
    title_y = min(title_y, (HEIGHT - 76) * SCALE)
    anchor_x = min(x - 18 * SCALE, (WIDTH - 12) * SCALE)
    draw.text((anchor_x, title_y), name, fill=color, font=title_font, anchor="ra")
    draw.text((anchor_x, title_y + (42 if active else 33) * SCALE), f"{au:.1f} AU", fill=LABEL, font=detail_font, anchor="ra")
    return draw

def render_map(active_name, active_position, active_color, twin_name=None, twin_position=None):
    """Draw where the spacecraft are today, seen from above the planets. Returns JPEG bytes."""
    image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _stars(draw, active_name)

    au, longitude = _place(active_position)
    twin = _place(twin_position) if twin_position else None

    # Turn the map so the two spacecraft sit either side of the horizontal axis.
    # Only the viewing direction changes; their true separation is preserved.
    spread = _angle_between(twin[1], longitude) if twin else 0
    active_angle = -spread / 2
    twin_angle = spread / 2

    sun_x, sun_y = SUN_X * SCALE, HEIGHT // 2 * SCALE

    for name, orbit_au in ORBITS:
        radius = _radius(orbit_au)
        draw.ellipse((sun_x - radius, sun_y - radius, sun_x + radius, sun_y + radius), outline=RING, width=SCALE)
        draw.text(
            (sun_x + radius * math.cos(-0.72), sun_y - radius * math.sin(-0.72) + 4 * SCALE),
            name, fill=LABEL, font=_font(21), anchor="lt",
        )

    radius = _radius(HELIOPAUSE_AU)
    _dashed_circle(draw, sun_x, sun_y, radius, (140, 118, 190), SCALE)
    draw.text(
        (sun_x + radius - 10 * SCALE, sun_y),
        "Edge of the Sun's influence", fill=(190, 170, 228), font=_font(21), anchor="rm",
    )

    earth = _radius(1)
    draw.ellipse((sun_x - earth, sun_y - earth, sun_x + earth, sun_y + earth), outline=(70, 110, 150), width=SCALE)
    _sun(image, sun_x, sun_y)
    draw = ImageDraw.Draw(image)
    draw.text((sun_x, sun_y + earth + 6 * SCALE), "Sun and Earth", fill=LABEL, font=_font(21), anchor="mt")

    if twin:
        draw = _craft(image, draw, sun_x, sun_y, twin_angle, twin[0], twin_name, MUTED_CRAFT, False)
    _craft(image, draw, sun_x, sun_y, active_angle, au, active_name, active_color, True)

    draw = ImageDraw.Draw(image)
    draw.text(
        (16 * SCALE, (HEIGHT - 12) * SCALE),
        "Today, seen from above the planets. Distances compressed.",
        fill=LABEL, font=_font(20), anchor="ld",
    )

    output = io.BytesIO()
    image.resize((WIDTH, HEIGHT), Image.LANCZOS).save(output, "JPEG", quality=86, optimize=True, progressive=True)
    return output.getvalue()
