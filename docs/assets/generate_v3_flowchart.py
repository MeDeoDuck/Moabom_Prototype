"""영상 선정 Agent v3 (coarse-to-fine) 플로우차트 PNG 생성기.

v1 생성기(generate_video_selection_flowchart.py)와 동일 팔레트. 두 그룹 패널로
"공유 후보 준비(LangGraph)"와 "v3 재선택"을 구분한다.

데스크탑(Ubuntu) 한글 폰트 사용 — 노트북(Windows)에서 돌릴 땐 FONT 경로만 교체.
출력: docs/assets/video_selection_agent_v3_flowchart.png
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── 팔레트 (v1 생성기와 동일) ───────────────────────────────
BG = "#F8F8F8"
NAVY = "#183098"
LIGHT = "#D8E0F0"
MID = "#3850B8"
GREY = "#808080"
# v3 그룹 강조용 (살짝 다른 톤으로 단계 구분)
V3FILL = "#DCEBE2"
V3EDGE = "#1E7A52"
PANEL = "#EEF1F8"
PANEL_V3 = "#E7F2EC"

W, H = 1480, 1860
SCALE = 2  # 슈퍼샘플링 후 축소 → 글자/선 또렷

_NANUM_B = "/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf"
_NANUM_R = "/usr/share/fonts/truetype/nanum/NanumSquareRoundR.ttf"


def f(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_NANUM_B if bold else _NANUM_R, size=size * SCALE)


def _center_text(d, cx, cy, lines, font, fill):
    if isinstance(lines, str):
        lines = lines.split("\n")
    asc, desc = font.getmetrics()
    lh = asc + desc
    total = lh * len(lines)
    y = cy - total / 2
    for ln in lines:
        l, t, r, b = d.textbbox((0, 0), ln, font=font)
        d.text((cx - (r - l) / 2, y), ln, font=font, fill=fill)
        y += lh


def box(d, cx, cy, w, h, label, *, fill=LIGHT, edge=NAVY, fsz=21, txt=NAVY, sub=None, rad=16):
    x0, y0, x1, y1 = (cx - w / 2) * SCALE, (cy - h / 2) * SCALE, (cx + w / 2) * SCALE, (cy + h / 2) * SCALE
    d.rounded_rectangle([x0, y0, x1, y1], radius=rad * SCALE, fill=fill, outline=edge, width=3 * SCALE)
    if sub:
        _center_text(d, cx * SCALE, (cy - 9) * SCALE, label, f(fsz), txt)
        _center_text(d, cx * SCALE, (cy + 13) * SCALE, sub, f(13, bold=False), GREY)
    else:
        _center_text(d, cx * SCALE, cy * SCALE, label, f(fsz), txt)


def diamond(d, cx, cy, w, h, label, *, fsz=18):
    pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)]
    d.polygon([(x * SCALE, y * SCALE) for x, y in pts], fill=LIGHT, outline=NAVY)
    # 두꺼운 테두리
    for i in range(len(pts)):
        a = (pts[i][0] * SCALE, pts[i][1] * SCALE)
        b = (pts[(i + 1) % len(pts)][0] * SCALE, pts[(i + 1) % len(pts)][1] * SCALE)
        d.line([a, b], fill=NAVY, width=3 * SCALE)
    _center_text(d, cx * SCALE, cy * SCALE, label, f(fsz), NAVY)


def pill(d, cx, cy, w, h, label):
    x0, y0, x1, y1 = (cx - w / 2) * SCALE, (cy - h / 2) * SCALE, (cx + w / 2) * SCALE, (cy + h / 2) * SCALE
    d.rounded_rectangle([x0, y0, x1, y1], radius=(h / 2) * SCALE, fill=MID, outline=NAVY, width=3 * SCALE)
    _center_text(d, cx * SCALE, cy * SCALE, label, f(22), "#FFFFFF")


def arrow(d, p0, p1, *, color=NAVY, label=None, lw=3, dashed=False):
    x0, y0 = p0[0] * SCALE, p0[1] * SCALE
    x1, y1 = p1[0] * SCALE, p1[1] * SCALE
    if dashed:
        # 간단 점선
        import math
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        steps = int(dist / (10 * SCALE))
        for i in range(steps):
            if i % 2 == 0:
                a = (x0 + dx * i / steps, y0 + dy * i / steps)
                b = (x0 + dx * (i + 1) / steps, y0 + dy * (i + 1) / steps)
                d.line([a, b], fill=color, width=lw * SCALE)
    else:
        d.line([(x0, y0), (x1, y1)], fill=color, width=lw * SCALE)
    # 화살촉
    import math
    ang = math.atan2(y1 - y0, x1 - x0)
    sz = 11 * SCALE
    d.polygon([
        (x1, y1),
        (x1 - sz * math.cos(ang - 0.4), y1 - sz * math.sin(ang - 0.4)),
        (x1 - sz * math.cos(ang + 0.4), y1 - sz * math.sin(ang + 0.4)),
    ], fill=color)
    if label:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        fnt = f(14, bold=True)
        l, t, r, b = d.textbbox((0, 0), label, font=fnt)
        pad = 5 * SCALE
        d.rectangle([mx - (r - l) / 2 - pad, my - (b - t) / 2 - pad, mx + (r - l) / 2 + pad, my + (b - t) / 2 + pad], fill=BG)
        d.text((mx - (r - l) / 2, my - (b - t) / 2), label, font=fnt, fill=MID)


def main() -> None:
    img = Image.new("RGB", (W * SCALE, H * SCALE), BG)
    d = ImageDraw.Draw(img)

    cx = 540          # 메인 컬럼 중심
    rx = 1130         # 우측 우회 컬럼
    lx = 175          # 좌측 relax
    NW, NH = 330, 60  # 노드 박스
    DW, DH = 250, 92  # 다이아몬드

    # 제목
    _center_text(d, (W / 2) * SCALE, 52 * SCALE, "영상 선정 Agent v3 — coarse-to-fine clustering", f(30), NAVY)

    # ── 그룹 패널 ──
    d.rounded_rectangle([(cx - 250) * SCALE, 188 * SCALE, (cx + 250) * SCALE, 760 * SCALE],
                        radius=22 * SCALE, fill=PANEL, outline=GREY, width=2 * SCALE)
    _center_text(d, cx * SCALE, 206 * SCALE, "공유 후보 준비  (LangGraph · v3 입력 + 정량 fallback)", f(15), GREY)
    d.rounded_rectangle([(cx - 250) * SCALE, 854 * SCALE, (cx + 250) * SCALE, 1672 * SCALE],
                        radius=22 * SCALE, fill=PANEL_V3, outline=V3EDGE, width=2 * SCALE)
    _center_text(d, cx * SCALE, 872 * SCALE, "v3 재선택  (coarse → fine → verify)", f(15), V3EDGE)

    # ── 노드 좌표 (y) ──
    ys = {
        "start": 130, "a1": 250, "a2": 322, "a3": 394, "a4": 478, "a6": 580, "a7": 652,
        "sw": 800, "b1": 912, "b2": 984, "b3": 1056, "b4": 1128, "b5": 1200, "b6": 1272,
        "b7": 1380, "b8": 1486, "cache": 1558, "end": 1720,
    }

    # ── 화살표 (노드 뒤에 깔리게 먼저) ──
    arrow(d, (cx, ys["start"] + 24), (cx, ys["a1"] - NH / 2))
    arrow(d, (cx, ys["a1"] + NH / 2), (cx, ys["a2"] - NH / 2))
    arrow(d, (cx, ys["a2"] + NH / 2), (cx, ys["a3"] - NH / 2))
    arrow(d, (cx, ys["a3"] + NH / 2), (cx, ys["a4"] - DH / 2))
    # relax 루프
    arrow(d, (cx - DW / 2, ys["a4"]), (lx, ys["a4"]), label="보완")
    box(d, lx, ys["a4"], 180, 52, "relax", fill=LIGHT, fsz=20)
    arrow(d, (lx, ys["a4"] - 26), (lx, ys["a3"]), )
    arrow(d, (lx, ys["a3"]), (cx - NW / 2, ys["a3"]))
    arrow(d, (cx, ys["a4"] + DH / 2), (cx, ys["a6"] - NH / 2), label="통과")
    arrow(d, (cx, ys["a6"] + NH / 2), (cx, ys["a7"] - NH / 2))
    arrow(d, (cx, ys["a7"] + NH / 2), (cx, ys["sw"] - DH / 2))
    # 분기
    arrow(d, (cx, ys["sw"] + DH / 2), (cx, ys["b1"] - NH / 2), label="v3_cluster (기본)")
    # v1_weighted bypass → 우측 → End
    arrow(d, (cx + DW / 2, ys["sw"]), (rx, ys["sw"]), label="v1_weighted")
    arrow(d, (rx, ys["sw"]), (rx, ys["end"]))
    arrow(d, (rx, ys["end"]), (cx + 120, ys["end"]))
    # v3 본류
    for a, b in [("b1", "b2"), ("b2", "b3"), ("b3", "b4"), ("b4", "b5"), ("b5", "b6")]:
        arrow(d, (cx, ys[a] + NH / 2), (cx, ys[b] - NH / 2))
    arrow(d, (cx, ys["b6"] + NH / 2), (cx, ys["b7"] - DH / 2))
    arrow(d, (cx, ys["b7"] + DH / 2), (cx, ys["b8"] - NH / 2), label="예")
    arrow(d, (cx, ys["b8"] + NH / 2), (cx, ys["cache"] - NH / 2))
    arrow(d, (cx, ys["cache"] + NH / 2), (cx, ys["end"] - 24))
    # B7 fallback → 우측 FB → End
    arrow(d, (cx + DW / 2, ys["b7"]), (rx, ys["b7"]), label="아니오/timeout")
    box(d, rx, ys["b8"], 210, 64, "정량 Top-K 유지", fill=LIGHT, sub="v1 fallback", fsz=18)
    arrow(d, (rx, ys["b7"]), (rx, ys["b8"] - 32))
    arrow(d, (rx, ys["b8"] + 32), (rx, ys["end"]))

    # ── 노드 그리기 ──
    pill(d, cx, ys["start"], 200, 50, "제품명")
    box(d, cx, ys["a1"], NW, NH, "fetch", sub="후보 풀 수집")
    box(d, cx, ys["a2"], NW, NH, "enrich", sub="채널 메타·구독자")
    box(d, cx, ys["a3"], NW, NH, "6차원 점수", sub="score_quantitative")
    diamond(d, cx, ys["a4"], DW, DH, "다양성\n필터")
    box(d, cx, ys["a6"], NW, NH, "scope_filter", sub="비교/랭킹 영상 제외 (GPU 워커)")
    box(d, cx, ys["a7"], NW, NH, "finalize", sub="정량 Top-K (LLM 불필요)")
    diamond(d, cx, ys["sw"], DW + 40, DH, "SELECTION_\nSTRATEGY")

    box(d, cx, ys["b1"], NW, NH, "lang_normalize", sub="영문만 한국어 번역 (mini)", fill=V3FILL, edge=V3EDGE)
    box(d, cx, ys["b2"], NW, NH, "coarse_cluster", sub="Qwen3 임베딩 → KMeans k=5", fill=V3FILL, edge=V3EDGE)
    box(d, cx, ys["b3"], NW, NH, "LLM#1 shortlist", sub="클러스터 라벨 + 클러스터당 2개 (~10)", fill=V3FILL, edge=V3EDGE)
    box(d, cx, ys["b4"], NW, NH, "fetch_transcripts", sub="캐시 우선 · first/mid/last 샘플링", fill=V3FILL, edge=V3EDGE)
    box(d, cx, ys["b5"], NW, NH, "LLM#2 final_select", sub="후보별 fit · depth · risk + 근거", fill=V3FILL, edge=V3EDGE)
    box(d, cx, ys["b6"], NW, NH, "코드 verifier", sub="scope0·mega≤2·non-mega≥1·채널캡·coverage", fill=V3FILL, edge=V3EDGE)
    diamond(d, cx, ys["b7"], DW + 40, DH, "정책 만족\nk개?")
    box(d, cx, ys["b8"], NW, NH, "v3 선택으로 교체", fill=V3FILL, edge=V3EDGE)
    box(d, cx, ys["cache"], NW, NH, "자막 캐시", sub="video_transcripts → 보고서 재사용", fill=V3FILL, edge=V3EDGE)
    pill(d, cx, ys["end"], 230, 50, "영상 + 근거")

    out = Path(__file__).resolve().parent / "video_selection_agent_v3_flowchart.png"
    img = img.resize((W, H), Image.LANCZOS)
    img.save(out)
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
