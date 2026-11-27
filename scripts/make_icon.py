"""生成应用图标：白底，黑色 "it"。

跑：python scripts/make_icon.py
输出到 app/src/main/res/mipmap-*/ic_launcher.png
"""

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "app", "src", "main", "res")

SIZES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
]


def pick_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def render(size, out_path):
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    font_path = pick_font()
    font = ImageFont.truetype(font_path, int(size * 0.52)) if font_path \
        else ImageFont.load_default()

    text = "it"
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (size - w) / 2 - bbox[0]
    y = (size - h) / 2 - bbox[1] - size * 0.02
    draw.text((x, y), text, font=font, fill=(17, 17, 17))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    print(out_path, size)


def main():
    for folder, size in SIZES.items():
        render(size, os.path.join(RES, folder, "ic_launcher.png"))
    render(512, os.path.join(ROOT, "dist", "icon-512.png"))


if __name__ == "__main__":
    main()
