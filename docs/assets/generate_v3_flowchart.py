"""영상 선정 Agent v3 (coarse-to-fine) 플로우차트 PNG 생성기 — 가로형 3행 스네이크.

v1 생성기와 동일 팔레트. 한 줄 LR 은 너무 길어 가독성이 떨어지므로 읽기 방향대로
꺾이는 3행(boustrophedon) 레이아웃을 쓴다:
  행1 (→) 공유 후보 준비   행2 (←) v3 coarse   행3 (→) v3 fine + verify

실질 병렬은 fetch_transcripts(ThreadPool×5) 하나 — 나머지는 데이터 의존 사슬이라
직렬. 그 점을 노드 주석으로 표기.

출력: docs/assets/video_selection_agent_v3_flowchart.png
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── 팔레트 (v1 생성기와 동일) ───────────────────────────────
BG = "#F8F8F8"
NAVY = "#183098"
LIGHT = "#D8E0F0"
MID = "#3850B8"
GREY = "#808080"
V3FILL = "#DCEBE2"
V3EDGE = "#1E7A52"
PANEL = "#EEF1F8"
PANEL_V3 = "#E7F2EC"
PARA = "#B85C00"  # 병렬 강조

W, H = 1960, 1120
SCALE = 2

_NANUM_B = "/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf"
_NANUM_R = "/usr/share/fonts/truetype/nanum/NanumSquareRoundR.ttf"


def f(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_NANUM_B if bold else _NANUM_R, size=size * SCALE)


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


def box(d, cx, cy, w, h, label, *, fill=LIGHT, edge=NAVY, fsz=20, sub=None):
    x0, y0, x1, y1 = (cx - w / 2) * SCALE, (cy - h / 2) * SCALE, (cx + w / 2) * SCALE, (cy + h / 2) * SCALE
    d.rounded_rectangle([x0, y0, x1, y1], radius=15 * SCALE, fill=fill, outline=edge, width=3 * SCALE)
    if sub:
        _ct(d, cx * SCALE, (cy - 9) * SCALE, label, f(fsz), NAVY)
        _ct(d, cx * SCALE, (cy + 12) * SCALE, sub, f(12, bold=False), GREY)
    else:
        _ct(d, cx * SCALE, cy * SCALE, label, f(fsz), NAVY)


def diamond(d, cx, cy, w, h, label, *, fsz=17):
    pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)]
    sp = [(x * SCALE, y * SCALE) for x, y in pts]
    d.polygon(sp, fill=LIGHT)
    for i in range(4):
        d.line([sp[i], sp[(i + 1) % 4]], fill=NAVY, width=3 * SCALE)
    _ct(d, cx * SCALE, cy * SCALE, label, f(fsz), NAVY)


def pill(d, cx, cy, w, h, label):
    x0, y0, x1, y1 = (cx - w / 2) * SCALE, (cy - h / 2) * SCALE, (cx + w / 2) * SCALE, (cy + h / 2) * SCALE
    d.rounded_rectangle([x0, y0, x1, y1], radius=(h / 2) * SCALE, fill=MID, outline=NAVY, width=3 * SCALE)
    _ct(d, cx * SCALE, cy * SCALE, label, f(21), "#FFFFFF")


def arrow(d, p0, p1, *, color=NAVY, label=None, lw=3, mids=None):
    pts = [p0] + (mids or []) + [p1]
    sp = [(x * SCALE, y * SCALE) for x, y in pts]
    d.line(sp, fill=color, width=lw * SCALE, joint="curve")
    x0, y0 = sp[-2]
    x1, y1 = sp[-1]
    ang = math.atan2(y1 - y0, x1 - x0)
    s = 11 * SCALE
    d.polygon([(x1, y1),
               (x1 - s * math.cos(ang - 0.4), y1 - s * math.sin(ang - 0.4)),
               (x1 - s * math.cos(ang + 0.4), y1 - s * math.sin(ang + 0.4))], fill=color)
    if label:
        # 라벨은 첫 세그먼트 중점
        mx, my = (sp[0][0] + sp[1][0]) / 2, (sp[0][1] + sp[1][1]) / 2
        fnt = f(13, bold=True)
        l, t, r, b = d.textbbox((0, 0), label, font=fnt)
        pad = 5 * SCALE
        d.rectangle([mx - (r - l) / 2 - pad, my - (b - t) / 2 - pad, mx + (r - l) / 2 + pad, my + (b - t) / 2 + pad], fill=BG)
        d.text((mx - (r - l) / 2, my - (b - t) / 2), label, font=fnt, fill=color)


def main() -> None:
    img = Image.new("RGB", (W * SCALE, H * SCALE), BG)
    d = ImageDraw.Draw(img)

    NW, NH = 230, 58
    _ct(d, (W / 2) * SCALE, 40 * SCALE, "영상 선정 Agent v3 — coarse-to-fine clustering", f(28), NAVY)

    # ── 그룹 패널 ──
    d.rounded_rectangle([55 * SCALE, 92 * SCALE, 1905 * SCALE, 268 * SCALE], radius=18 * SCALE, fill=PANEL, outline=GREY, width=2 * SCALE)
    _ct(d, 300 * SCALE, 110 * SCALE, "공유 후보 준비 (LangGraph · v3 입력 + 정량 fallback)", f(14), GREY)
    d.rounded_rectangle([55 * SCALE, 360 * SCALE, 1905 * SCALE, 1010 * SCALE], radius=18 * SCALE, fill=PANEL_V3, outline=V3EDGE, width=2 * SCALE)
    _ct(d, 230 * SCALE, 378 * SCALE, "v3 재선택 (coarse → fine → verify)", f(14), V3EDGE)

    # ── 행1 (→) 공유 후보 준비 ──
    r1 = 190
    pill(d, 120, r1, 175, 48, "제품명")
    box(d, 300, r1, NW, NH, "fetch", sub="후보 풀 수집")
    box(d, 495, r1, NW, NH, "enrich", sub="채널 메타·구독자")
    box(d, 695, r1, NW, NH, "6차원 점수", sub="score_quantitative")
    diamond(d, 895, r1, 200, 84, "다양성\n필터")
    box(d, 1110, r1, NW, NH, "scope_filter", sub="비교영상 제외(GPU 워커)")
    box(d, 1330, r1, NW, NH, "finalize", sub="정량 Top-K (LLM X)")
    diamond(d, 1600, r1, 230, 92, "SELECTION_\nSTRATEGY")

    arrow(d, (207, r1), (300 - NW / 2, r1))
    for a, b in [(300, 495), (495, 695)]:
        arrow(d, (a + NW / 2, r1), (b - NW / 2, r1))
    arrow(d, (695 + NW / 2, r1), (895 - 100, r1))
    arrow(d, (895 + 100, r1), (1110 - NW / 2, r1), label="통과")
    arrow(d, (1110 + NW / 2, r1), (1330 - NW / 2, r1))
    arrow(d, (1330 + NW / 2, r1), (1600 - 115, r1))
    # relax 루프 (다양성 아래 짧게)
    box(d, 760, 252, 150, 40, "relax", fsz=18)
    arrow(d, (895, r1 + 42), (835, 252), label="보완")
    arrow(d, (685, 252), (695, r1 + NH / 2))

    # ── 행1 → 행2 : SW 에서 v3 분기(아래로) ──
    r2 = 510
    arrow(d, (1600, r1 + 46), (1600, r2 - NH / 2), label="v3_cluster (기본)")
    # v1_weighted bypass → 우측 → End(행3)
    r3 = 820
    end_x = 1640
    arrow(d, (1600 + 115, r1), (1850, r1), label="v1_weighted")
    arrow(d, (1850, r1), (1850, r3), mids=[(1850, r3)])
    arrow(d, (1850, r3), (end_x + 110, r3))

    # ── 행2 (←) v3 coarse ──
    box(d, 1600, r2, NW, NH, "lang_normalize", sub="영문만 번역 (mini)", fill=V3FILL, edge=V3EDGE)
    box(d, 1230, r2, NW + 30, NH, "coarse_cluster", sub="Qwen3 임베딩 → KMeans k=5", fill=V3FILL, edge=V3EDGE)
    box(d, 840, r2, NW + 20, NH, "LLM#1 shortlist", sub="클러스터 라벨 + 클러스터당 2개", fill=V3FILL, edge=V3EDGE)
    box(d, 460, r2, NW, NH, "fetch_transcripts", sub="first/mid/last · 캐시우선", fill=V3FILL, edge=V3EDGE)
    # 병렬 강조 배지
    _ct(d, 460 * SCALE, (r2 + 44) * SCALE, "⇄ 병렬 ×5", f(13), PARA)
    arrow(d, (1600 - NW / 2, r2), (1230 + (NW + 30) / 2, r2))
    arrow(d, (1230 - (NW + 30) / 2, r2), (840 + (NW + 20) / 2, r2))
    arrow(d, (840 - (NW + 20) / 2, r2), (460 + NW / 2, r2))

    # ── 행2 → 행3 (좌측에서 내려 L→R) ──
    arrow(d, (460, r2 + NH / 2), (460, r3 - NH / 2))

    # ── 행3 (→) v3 fine + verify ──
    box(d, 460, r3, NW + 20, NH, "LLM#2 final_select", sub="후보별 fit·depth·risk", fill=V3FILL, edge=V3EDGE)
    box(d, 760, r3, NW, NH, "코드 verifier", sub="scope0·tier·채널·coverage", fill=V3FILL, edge=V3EDGE)
    diamond(d, 1010, r3, 175, 88, "정책\n만족?")
    box(d, 1280, r3 - 36, NW + 10, NH, "v3 교체 + 자막캐시", fill=V3FILL, edge=V3EDGE, fsz=18)
    box(d, 1280, r3 + 56, NW + 10, 50, "정량 Top-K 유지", fill=LIGHT, fsz=17, sub="fallback")
    pill(d, end_x, r3, 200, 48, "영상 + 근거")

    arrow(d, (460 + (NW + 20) / 2, r3), (760 - NW / 2, r3))
    arrow(d, (760 + NW / 2, r3), (1010 - 88, r3))
    arrow(d, (1010, r3 - 44), (1280, r3 - 36), label="예")
    arrow(d, (1010 + 88, r3), (1280 - (NW + 10) / 2, r3 + 56), label="아니오/timeout")
    arrow(d, (1280 + (NW + 10) / 2, r3 - 36), (end_x - 100, r3 - 8))
    arrow(d, (1280 + (NW + 10) / 2, r3 + 56), (end_x - 100, r3 + 8))

    out = Path(__file__).resolve().parent / "video_selection_agent_v3_flowchart.png"
    img.resize((W, H), Image.LANCZOS).save(out)
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
