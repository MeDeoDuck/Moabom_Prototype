"""영상 선정 Agent v3 (coarse-to-fine) 플로우차트 PNG 생성기 — 가로형 v3 단일 흐름.

기본 동작이 v3 이므로 SELECTION_STRATEGY 분기·v1 fallback 은 그림에서 생략하고
핵심 v3 경로만 2행 스네이크로 표현(가독성). v1 정량 fallback 은 코드상 안전망으로
남아있으나 본류가 아니라 미표기.

출력: docs/assets/video_selection_agent_v3_flowchart.png
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = "#F8F8F8"
NAVY = "#183098"
LIGHT = "#D8E0F0"
MID = "#3850B8"
GREY = "#808080"
V3FILL = "#DCEBE2"
V3EDGE = "#1E7A52"
PARA = "#B85C00"

W, H = 1480, 600
SCALE = 2
_NB = "/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf"
_NR = "/usr/share/fonts/truetype/nanum/NanumSquareRoundR.ttf"


def f(size, bold=True):
    return ImageFont.truetype(_NB if bold else _NR, size=size * SCALE)


def _ct(d, cx, cy, lines, font, fill):
    if isinstance(lines, str):
        lines = lines.split("\n")
    asc, desc = font.getmetrics()
    lh = asc + desc
    y = cy - lh * len(lines) / 2
    for ln in lines:
        l, t, r, b = d.textbbox((0, 0), ln, font=font)
        d.text((cx - (r - l) / 2, y), ln, font=font, fill=fill)
        y += lh


def box(d, cx, cy, w, h, label, *, fill=LIGHT, edge=NAVY, fsz=19, sub=None):
    x0, y0, x1, y1 = (cx - w / 2) * SCALE, (cy - h / 2) * SCALE, (cx + w / 2) * SCALE, (cy + h / 2) * SCALE
    d.rounded_rectangle([x0, y0, x1, y1], radius=14 * SCALE, fill=fill, outline=edge, width=3 * SCALE)
    if sub:
        _ct(d, cx * SCALE, (cy - 8) * SCALE, label, f(fsz), NAVY)
        _ct(d, cx * SCALE, (cy + 12) * SCALE, sub, f(11, bold=False), GREY)
    else:
        _ct(d, cx * SCALE, cy * SCALE, label, f(fsz), NAVY)


def diamond(d, cx, cy, w, h, label, *, fsz=16):
    pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)]
    sp = [(x * SCALE, y * SCALE) for x, y in pts]
    d.polygon(sp, fill=LIGHT)
    for i in range(4):
        d.line([sp[i], sp[(i + 1) % 4]], fill=NAVY, width=3 * SCALE)
    _ct(d, cx * SCALE, cy * SCALE, label, f(fsz), NAVY)


def pill(d, cx, cy, w, h, label):
    x0, y0, x1, y1 = (cx - w / 2) * SCALE, (cy - h / 2) * SCALE, (cx + w / 2) * SCALE, (cy + h / 2) * SCALE
    d.rounded_rectangle([x0, y0, x1, y1], radius=(h / 2) * SCALE, fill=MID, outline=NAVY, width=3 * SCALE)
    _ct(d, cx * SCALE, cy * SCALE, label, f(19), "#FFFFFF")


def arrow(d, p0, p1, *, color=NAVY, label=None, mids=None, lw=3):
    pts = [p0] + (mids or []) + [p1]
    sp = [(x * SCALE, y * SCALE) for x, y in pts]
    d.line(sp, fill=color, width=lw * SCALE, joint="curve")
    x0, y0 = sp[-2]
    x1, y1 = sp[-1]
    ang = math.atan2(y1 - y0, x1 - x0)
    s = 10 * SCALE
    d.polygon([(x1, y1),
               (x1 - s * math.cos(ang - 0.4), y1 - s * math.sin(ang - 0.4)),
               (x1 - s * math.cos(ang + 0.4), y1 - s * math.sin(ang + 0.4))], fill=color)
    if label:
        mx, my = (sp[0][0] + sp[1][0]) / 2, (sp[0][1] + sp[1][1]) / 2
        fnt = f(12, bold=True)
        l, t, r, b = d.textbbox((0, 0), label, font=fnt)
        pad = 4 * SCALE
        d.rectangle([mx - (r - l) / 2 - pad, my - (b - t) / 2 - pad, mx + (r - l) / 2 + pad, my + (b - t) / 2 + pad], fill=BG)
        d.text((mx - (r - l) / 2, my - (b - t) / 2), label, font=fnt, fill=MID)


def main():
    img = Image.new("RGB", (W * SCALE, H * SCALE), BG)
    d = ImageDraw.Draw(img)
    _ct(d, (W / 2) * SCALE, 38 * SCALE, "영상 선정 Agent v3 — coarse-to-fine clustering", f(26), NAVY)

    NH = 56
    r1, r2 = 175, 430

    # ── 행1 (→) ──
    pill(d, 105, r1, 150, 46, "제품명")
    box(d, 290, r1, 200, NH, "fetch · enrich", sub="후보 수집·메타")
    box(d, 500, r1, 180, NH, "6차원 점수")
    diamond(d, 690, r1, 175, 80, "다양성\n필터")
    box(d, 900, r1, 200, NH, "scope_filter", sub="비교영상 제외")
    box(d, 1180, r1, 270, NH, "coarse_cluster", sub="번역 → Qwen3 임베딩 → KMeans k=5", fill=V3FILL, edge=V3EDGE)

    arrow(d, (180, r1), (190, r1))
    arrow(d, (390, r1), (410, r1))
    arrow(d, (590, r1), (690 - 88, r1))
    arrow(d, (690 + 88, r1), (800, r1), label="통과")
    arrow(d, (1000, r1), (1045, r1))
    # relax 루프
    box(d, 500, 258, 130, 38, "relax", fsz=16)
    arrow(d, (690, r1 + 40), (565, 258), label="보완")
    arrow(d, (435, 258), (500, r1 + NH / 2))

    # ── 행1 → 행2 (coarse_cluster 아래로) ──
    arrow(d, (1180, r1 + NH / 2), (1180, r2 - NH / 2))

    # ── 행2 (←) ──
    box(d, 1180, r2, 230, NH, "LLM#1 shortlist", sub="클러스터당 2개", fill=V3FILL, edge=V3EDGE)
    box(d, 905, r2, 210, NH, "fetch_transcripts", sub="캐시 우선", fill=V3FILL, edge=V3EDGE)
    _ct(d, 905 * SCALE, (r2 + 42) * SCALE, "⇄ 병렬", f(12), PARA)
    box(d, 650, r2, 220, NH, "LLM#2 final_select", sub="후보별 fit·depth·risk", fill=V3FILL, edge=V3EDGE)
    box(d, 400, r2, 190, NH, "코드 verifier", sub="정책 만족 Top-K", fill=V3FILL, edge=V3EDGE)
    box(d, 200, r2, 150, NH, "자막 캐시", sub="보고서 재사용", fill=V3FILL, edge=V3EDGE)
    pill(d, 90, r2 + 120, 170, 46, "영상 + 근거")

    arrow(d, (1180 - 115, r2), (905 + 105, r2))
    arrow(d, (905 - 105, r2), (650 + 110, r2))
    arrow(d, (650 - 110, r2), (400 + 95, r2))
    arrow(d, (400 - 95, r2), (200 + 75, r2))
    arrow(d, (200, r2 + NH / 2), (90, r2 + 120 - 23), mids=[(200, r2 + 90)])

    out = Path(__file__).resolve().parent / "video_selection_agent_v3_flowchart.png"
    img.resize((W, H), Image.LANCZOS).save(out)
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
