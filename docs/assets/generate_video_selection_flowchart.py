"""중간발표 page 15 영상 선정 AGENT 플로우차트 PNG 생성기.

색상은 종설 중간발표 초안 덱(page 14, 16)에서 추출한 정확한 hex로 고정:
  - 배경        #F8F8F8
  - 진한 네이비  #183098 (테두리, 텍스트, 화살표)
  - 연한 블루   #D8E0F0 (박스 채움)
  - 미드 블루   #3850B8 (강조 라벨, True/False, ★)
  - 회색       #808080 (헤더, 영문 함수명)

출력: docs/assets/video_selection_agent_flowchart.png (1920x1080)
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── 팔레트 ─────────────────────────────────────────────────────
BG = "#F8F8F8"
NAVY = "#183098"
LIGHT = "#D8E0F0"
MID = "#3850B8"
GREY = "#808080"

W, H = 1920, 1080

FONT = "C:/Windows/Fonts/malgun.ttf"
FONT_BD = "C:/Windows/Fonts/malgunbd.ttf"


def f(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BD if bold else FONT, size=size)


# ── 헬퍼 ───────────────────────────────────────────────────────
def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t


def text_centered(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    w, h = text_size(draw, text, font)
    draw.text((cx - w // 2, cy - h // 2), text, font=font, fill=fill)


def rounded_box(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    w: int,
    h: int,
    radius: int = 14,
    border: int = 3,
) -> tuple[int, int, int, int]:
    x0, y0 = cx - w // 2, cy - h // 2
    x1, y1 = cx + w // 2, cy + h // 2
    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=radius,
        fill=LIGHT,
        outline=NAVY,
        width=border,
    )
    return x0, y0, x1, y1


def diamond(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    w: int,
    h: int,
    border: int = 3,
) -> None:
    pts = [(cx, cy - h // 2), (cx + w // 2, cy), (cx, cy + h // 2), (cx - w // 2, cy)]
    draw.polygon(pts, fill=LIGHT, outline=NAVY)
    # PIL polygon outline width is always 1; manually thicken with line
    pts_closed = pts + [pts[0]]
    for i in range(4):
        draw.line([pts_closed[i], pts_closed[i + 1]], fill=NAVY, width=border)


def arrow(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    width: int = 3,
    dashed: bool = False,
    color: str = NAVY,
) -> None:
    if dashed:
        # manually draw dashed segments
        dash_len = 10
        gap_len = 8
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        n = max(1, int(dist // (dash_len + gap_len)))
        ux, uy = dx / dist, dy / dist
        for i in range(n + 1):
            sx = x0 + ux * i * (dash_len + gap_len)
            sy = y0 + uy * i * (dash_len + gap_len)
            ex = sx + ux * dash_len
            ey = sy + uy * dash_len
            # clamp last seg
            if (ex - x0) * ux + (ey - y0) * uy > dist:
                ex, ey = x1, y1
            draw.line([(sx, sy), (ex, ey)], fill=color, width=width)
    else:
        draw.line([(x0, y0), (x1, y1)], fill=color, width=width)
    # arrow head
    angle = math.atan2(y1 - y0, x1 - x0)
    head_len = 14
    head_w = 9
    bx = x1 - head_len * math.cos(angle)
    by = y1 - head_len * math.sin(angle)
    left = (bx + head_w * math.sin(angle), by - head_w * math.cos(angle))
    right = (bx - head_w * math.sin(angle), by + head_w * math.cos(angle))
    draw.polygon([(x1, y1), left, right], fill=color)


def node(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    w: int,
    h: int,
    step: str,
    label_ko: str,
    label_en: str,
    note: str | None = None,
    star: bool = False,
) -> None:
    rounded_box(draw, cx, cy, w, h)
    # step number top-left chip
    chip_text = step
    chip_font = f(20, bold=True)
    cw, ch = text_size(draw, chip_text, chip_font)
    chip_pad_x, chip_pad_y = 10, 4
    chip_x = cx - w // 2 + 12
    chip_y = cy - h // 2 + 10
    draw.rounded_rectangle(
        (chip_x, chip_y, chip_x + cw + chip_pad_x * 2, chip_y + ch + chip_pad_y * 2),
        radius=8,
        fill=NAVY,
    )
    draw.text((chip_x + chip_pad_x, chip_y + chip_pad_y - 2), chip_text, font=chip_font, fill="#FFFFFF")

    # Korean label
    text_centered(draw, cx, cy - 5, label_ko, f(26, bold=True), NAVY)
    # English function name
    text_centered(draw, cx, cy + 26, label_en, f(18), GREY)
    # optional note line
    if note:
        text_centered(draw, cx, cy + 50, note, f(15), MID)

    if star:
        # star + label above
        star_y = cy - h // 2 - 28
        text_centered(draw, cx, star_y, "★  LLM × 1", f(18, bold=True), MID)


def diamond_node(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    w: int,
    h: int,
    step: str,
    label_ko: str,
    label_en: str,
    note: str | None = None,
) -> None:
    diamond(draw, cx, cy, w, h)
    chip_font = f(18, bold=True)
    cw, ch = text_size(draw, step, chip_font)
    chip_x = cx - cw // 2 - 8
    chip_y = cy - h // 2 + 14
    draw.rounded_rectangle(
        (chip_x, chip_y, chip_x + cw + 16, chip_y + ch + 8),
        radius=8,
        fill=NAVY,
    )
    draw.text((chip_x + 8, chip_y + 2), step, font=chip_font, fill="#FFFFFF")

    text_centered(draw, cx, cy + 4, label_ko, f(22, bold=True), NAVY)
    text_centered(draw, cx, cy + 30, label_en, f(15), GREY)
    if note:
        text_centered(draw, cx, cy + 52, note, f(13), MID)


def end_pill(draw: ImageDraw.ImageDraw, cx: int, cy: int, label: str = "END") -> None:
    w, h = 120, 70
    x0, y0, x1, y1 = cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2
    draw.rounded_rectangle((x0, y0, x1, y1), radius=35, fill=NAVY, outline=NAVY, width=3)
    text_centered(draw, cx, cy, label, f(26, bold=True), "#FFFFFF")


# ── 메인 그리기 ───────────────────────────────────────────────
def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # 헤더
    text_size_l = f(22)
    draw.text((60, 38), "2026-1 인공지능종합설계", font=text_size_l, fill=GREY)
    right = "03 전체 구조 및 핵심 모듈"
    rw, _ = text_size(draw, right, text_size_l)
    draw.text((W - 60 - rw, 38), right, font=text_size_l, fill=GREY)

    # 좌측 윗쪽 가는 가로선
    draw.line([(60, 80), (W - 60, 80)], fill="#D0D0D0", width=1)

    # 섹션 라벨 + 제목
    draw.text((60, 100), "핵심 모듈 1", font=f(24), fill=GREY)
    draw.text((60, 140), "영상 선정 AGENT", font=f(64, bold=True), fill=NAVY)

    # ── 메인 파이프라인 ──────────────────────────────────────
    # 7 process + 1 END,  centers
    BOX_W, BOX_H = 200, 130
    DIAMOND_W, DIAMOND_H = 200, 150
    centers_x = [165, 395, 625, 855, 1085, 1315, 1545]
    end_cx = 1780
    row_y = 410

    # 노드 정의
    nodes = [
        ("Step 1", "초기 후보군 수집", "fetch_candidates", "YouTube 4종 쿼리"),
        ("Step 2", "메타데이터 보강", "enrich_metadata", "channels.list 보강"),
        ("Step 3", "정량 스코어링", "score_quantitative", "6차원 가중합"),
        # Step 4 — diamond
        ("Step 5", "LLM Re-rank", "llm_rerank", "Azure GPT-4.1-mini"),
        ("Step 6", "최종 선정", "finalize_selection", "top-k = 3~10"),
        ("Step 7", "Rationale 생성", "generate_rationale", "2~3문장 한국어"),
    ]

    # Step 1
    node(draw, centers_x[0], row_y, BOX_W, BOX_H, *nodes[0])
    # Step 2
    node(draw, centers_x[1], row_y, BOX_W, BOX_H, *nodes[1])
    # Step 3
    node(draw, centers_x[2], row_y, BOX_W, BOX_H, *nodes[2])
    # Step 4 diamond
    diamond_node(
        draw,
        centers_x[3],
        row_y,
        DIAMOND_W,
        DIAMOND_H,
        "Step 4",
        "다양성 필터",
        "diversity_filter",
        "max_per_channel=2",
    )
    # Step 5 (LLM)
    node(draw, centers_x[4], row_y, BOX_W, BOX_H, *nodes[3], star=True)
    # Step 6
    node(draw, centers_x[5], row_y, BOX_W, BOX_H, *nodes[4])
    # Step 7 (LLM)
    node(draw, centers_x[6], row_y, BOX_W, BOX_H, *nodes[5], star=True)
    # END pill
    end_pill(draw, end_cx, row_y)

    # 화살표 — 메인 흐름
    box_half = BOX_W // 2
    diamond_half = DIAMOND_W // 2
    pill_half = 60
    pairs = [
        (centers_x[0] + box_half, centers_x[1] - box_half, row_y, row_y),  # 1→2
        (centers_x[1] + box_half, centers_x[2] - box_half, row_y, row_y),  # 2→3
        (centers_x[2] + box_half, centers_x[3] - diamond_half, row_y, row_y),  # 3→4
        (centers_x[3] + diamond_half, centers_x[4] - box_half, row_y, row_y),  # 4→5 (True)
        (centers_x[4] + box_half, centers_x[5] - box_half, row_y, row_y),  # 5→6
        (centers_x[5] + box_half, centers_x[6] - box_half, row_y, row_y),  # 6→7
        (centers_x[6] + box_half, end_cx - pill_half, row_y, row_y),  # 7→END
    ]
    for x0, x1, y0, y1 in pairs:
        arrow(draw, x0, y0, x1, y1)

    # True 라벨 (4→5 화살표 위)
    true_x = (centers_x[3] + diamond_half + centers_x[4] - box_half) // 2
    text_centered(draw, true_x, row_y - 22, "True", f(18, bold=True), MID)

    # ── Step 4a (relax_constraints) — Step 4 아래 ─────────────
    relax_cx, relax_cy = centers_x[3], 720
    relax_w, relax_h = 320, 110
    rounded_box(draw, relax_cx, relax_cy, relax_w, relax_h)
    chip_text = "Step 4a"
    chip_font = f(18, bold=True)
    cw, ch = text_size(draw, chip_text, chip_font)
    cx_chip = relax_cx - relax_w // 2 + 14
    cy_chip = relax_cy - relax_h // 2 + 12
    draw.rounded_rectangle(
        (cx_chip, cy_chip, cx_chip + cw + 16, cy_chip + ch + 8),
        radius=8,
        fill=NAVY,
    )
    draw.text((cx_chip + 8, cy_chip + 2), chip_text, font=chip_font, fill="#FFFFFF")
    text_centered(draw, relax_cx, relax_cy - 5, "제약 완화", f(24, bold=True), NAVY)
    text_centered(draw, relax_cx, relax_cy + 20, "relax_constraints", f(16), GREY)
    text_centered(
        draw,
        relax_cx,
        relax_cy + 42,
        "max_per_channel +1 · mega ratio +0.2 · ≤1회",
        f(14),
        MID,
    )

    # 4 → 4a (False)
    arrow(draw, relax_cx, row_y + DIAMOND_H // 2, relax_cx, relax_cy - relax_h // 2)
    text_centered(draw, relax_cx + 28, (row_y + DIAMOND_H // 2 + relax_cy - relax_h // 2) // 2, "False", f(18, bold=True), MID)

    # 4a → 3 (loop back, L자 경로): 4a 좌측 → 좌로 → 위로 → 3 하단
    loop_x = relax_cx - relax_w // 2 - 60  # 4a 왼쪽으로 충분히 빠진 라우팅 채널
    # 4a 왼쪽 가장자리에서 채널까지 수평 이동
    draw.line([(relax_cx - relax_w // 2, relax_cy), (loop_x, relax_cy)], fill=NAVY, width=3)
    # 채널을 따라 위로
    draw.line([(loop_x, relax_cy), (loop_x, row_y + BOX_H // 2 + 30)], fill=NAVY, width=3)
    # 채널에서 Step 3 하단 중심으로 수평 이동
    draw.line([(loop_x, row_y + BOX_H // 2 + 30), (centers_x[2], row_y + BOX_H // 2 + 30)], fill=NAVY, width=3)
    # Step 3 하단으로 진입 (화살촉 포함)
    arrow(draw, centers_x[2], row_y + BOX_H // 2 + 30 + 1, centers_x[2], row_y + BOX_H // 2 + 2)
    text_centered(
        draw,
        loop_x - 40,
        (relax_cy + row_y + BOX_H // 2 + 30) // 2,
        "재스코어링 루프",
        f(15),
        MID,
    )

    # ── Step 1에서 후보=0 → END (점선 분기) ──────────────────
    # Step 1 아래로 점선 → 작은 END(후보 없음) 박스
    early_cx, early_cy = centers_x[0], 720
    early_w, early_h = 240, 70
    x0, y0 = early_cx - early_w // 2, early_cy - early_h // 2
    x1, y1 = early_cx + early_w // 2, early_cy + early_h // 2
    draw.rounded_rectangle((x0, y0, x1, y1), radius=35, fill="#FFFFFF", outline=NAVY, width=3)
    text_centered(draw, early_cx, early_cy, "END (후보 없음)", f(20, bold=True), NAVY)
    arrow(draw, centers_x[0], row_y + BOX_H // 2, early_cx, early_cy - early_h // 2, dashed=True)
    text_centered(draw, centers_x[0] + 60, (row_y + BOX_H // 2 + early_cy - early_h // 2) // 2, "후보 = 0", f(15), MID)

    # ── 하단 정보 띠 (가중치 / 편향 완화) ───────────────────
    strip_y = 880
    strip_h = 170

    # Box A: 정량 6차원 가중치
    bx0 = 70
    bx1 = 920
    by0 = strip_y
    by1 = strip_y + strip_h
    draw.rounded_rectangle((bx0, by0, bx1, by1), radius=18, fill="#FFFFFF", outline=NAVY, width=2)
    draw.text((bx0 + 22, by0 + 14), "정량 스코어 6차원 (가중치)", font=f(22, bold=True), fill=NAVY)
    weights = [
        ("relevance", "0.30"),
        ("engagement", "0.15"),
        ("recency", "0.10"),
        ("channel_anti_bias", "0.20"),
        ("duration_fit", "0.10"),
        ("llm_topical_fit", "0.15"),
    ]
    cell_w = (bx1 - bx0 - 40) // 3
    cell_h = 50
    grid_x0 = bx0 + 22
    grid_y0 = by0 + 60
    for i, (name, val) in enumerate(weights):
        col = i % 3
        row = i // 3
        cx0 = grid_x0 + col * cell_w
        cy0 = grid_y0 + row * cell_h
        draw.rounded_rectangle(
            (cx0, cy0, cx0 + cell_w - 14, cy0 + cell_h - 8),
            radius=10,
            fill=LIGHT,
            outline=NAVY,
            width=2,
        )
        draw.text((cx0 + 12, cy0 + 12), name, font=f(17), fill=NAVY)
        # value right-aligned
        vw, _ = text_size(draw, val, f(20, bold=True))
        draw.text((cx0 + cell_w - 14 - vw - 12, cy0 + 8), val, font=f(20, bold=True), fill=MID)

    # Box B: 편향 완화
    bx0 = 1000
    bx1 = 1850
    draw.rounded_rectangle((bx0, by0, bx1, by1), radius=18, fill="#FFFFFF", outline=NAVY, width=2)
    draw.text((bx0 + 22, by0 + 14), "편향 완화 4축", font=f(22, bold=True), fill=NAVY)
    bias_items = [
        "다중 쿼리 다양화",
        "채널 상한 (max=2)",
        "티어 쿼터 (mega ≤ 40%)",
        "anti-mega 가중치",
    ]
    cell_w = (bx1 - bx0 - 40) // 2
    cell_h = 50
    grid_x0 = bx0 + 22
    grid_y0 = by0 + 60
    for i, label in enumerate(bias_items):
        col = i % 2
        row = i // 2
        cx0 = grid_x0 + col * cell_w
        cy0 = grid_y0 + row * cell_h
        draw.rounded_rectangle(
            (cx0, cy0, cx0 + cell_w - 14, cy0 + cell_h - 8),
            radius=10,
            fill=LIGHT,
            outline=NAVY,
            width=2,
        )
        # bullet
        draw.ellipse((cx0 + 14, cy0 + 18, cx0 + 22, cy0 + 26), fill=MID)
        draw.text((cx0 + 32, cy0 + 12), label, font=f(18, bold=True), fill=NAVY)

    # 좌측 작은 ">" 셰브론 장식 (페이지 14, 16 스타일)
    chev_color = "#E0E8F8"
    pts = [(0, 320), (60, 380), (0, 440)]
    draw.polygon(pts, fill=chev_color)
    pts = [(W, 660), (W - 60, 720), (W, 780)]
    draw.polygon(pts, fill=chev_color)

    # 출력
    out = Path(__file__).parent / "video_selection_agent_flowchart.png"
    img.save(out, "PNG")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
