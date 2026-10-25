# -*- coding: utf-8 -*-
"""会ごとのホーム画面のアプリ（PWA）の材料を作る。kai/g/<会>/taikai.json の short・group・color・pai から、
同じフォルダへ manifest.json とアイコン（icon-512.png・icon-192.png・icon-180.png）を書く。
アイコンは、会の色の地に白い麻雀牌を置き、牌の字（pai）を描く。字体は Windows の Yu Gothic の太字を読むだけで使う。

使い方:
  python kai/tools/make_pwa.py            … すべての会（kai/g/*/）を作り直す
  python kai/tools/make_pwa.py hayakawa   … 1つの会だけ"""
import json, re, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
KAI = Path(__file__).resolve().parents[1]
FONTS = [Path("C:/Windows/Fonts/YuGothB.ttc"), Path("C:/Windows/Fonts/BIZ-UDGothicB.ttc"), Path("C:/Windows/Fonts/meiryob.ttc")]
PAI_COLOR = {"中": "#c8102e", "発": "#127a3a", "白": "#2a4d9b"}   # 牌の字の色（ほかの字は会の色）
SIZES = {"icon-512.png": 512, "icon-192.png": 192, "icon-180.png": 180}
SS = 4   # 4倍で描いて縮める（線をなめらかにする）


def font(px):
    for f in FONTS:
        if f.exists():
            return ImageFont.truetype(str(f), px)
    raise SystemExit("字体が見つからない（Yu Gothic などの太字）")


def icon(color, pai):
    S = 512 * SS
    im = Image.new("RGB", (S, S), color)
    d = ImageDraw.Draw(im)
    # 牌は、丸いマスクで切られても欠けない大きさ（中心から 0.4 の円の内側）に収める
    w, h, r = int(S * 0.47), int(S * 0.60), int(S * 0.06)
    x0, y0 = (S - w) // 2, (S - h) // 2 - int(S * 0.012)
    edge = int(S * 0.028)
    d.rounded_rectangle([x0, y0 + edge, x0 + w, y0 + h + edge], r, fill="#d8d2c2")   # 牌の厚み
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], r, fill="#fbfaf6")
    f = font(int(S * 0.34))
    ink = PAI_COLOR.get(pai, color)
    bx = d.textbbox((0, 0), pai, font=f)
    tx = x0 + (w - (bx[2] - bx[0])) // 2 - bx[0]
    ty = y0 + (h - (bx[3] - bx[1])) // 2 - bx[1]
    d.text((tx, ty), pai, font=f, fill=ink)
    return im


def make(gdir):
    cfg = json.loads((gdir / "taikai.json").read_text(encoding="utf-8"))
    g = gdir.name
    color = cfg.get("color") or "#7a1a1a"
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise SystemExit(f"{g}: color は #RRGGBB")
    pai = (cfg.get("pai") or "中")[:1]
    big = icon(color, pai)
    for name, px in SIZES.items():
        big.resize((px, px), Image.LANCZOS).save(gdir / name, optimize=True)
    # 開く先は組み合わせページ。halu は ?g= を付けない（いままでの URL のまま）
    start = "../../" if g == "halu" else f"../../?g={g}"
    man = {
        "id": f"/mahjong/kai/?g={g}",
        "name": (cfg.get("group") or cfg.get("title") or g) + "（組み合わせと点数）",
        "short_name": cfg.get("short") or cfg.get("group") or g,
        "lang": "ja",
        "start_url": start,
        "scope": "../../",
        "display": "standalone",
        "background_color": "#f7f7f5",
        "theme_color": color,
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    (gdir / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK {g}: manifest.json・{'・'.join(SIZES)}（{man['short_name']}・{color}・{pai}）")


def main():
    names = sys.argv[1:] or sorted(p.name for p in (KAI / "g").iterdir() if (p / "taikai.json").exists())
    for n in names:
        if not re.fullmatch(r"[a-z0-9-]{1,20}", n) or not (KAI / "g" / n / "taikai.json").exists():
            raise SystemExit(f"会 {n} の taikai.json がない")
        make(KAI / "g" / n)


if __name__ == "__main__":
    main()
