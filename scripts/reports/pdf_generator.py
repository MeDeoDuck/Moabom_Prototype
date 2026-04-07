"""
PDF report generation service
"""
from io import BytesIO
from pathlib import Path


def render_report_pdf(report_title: str, report_text: str) -> bytes:
    """Render report text into a downloadable PDF with Korean support and auto page breaks."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as e:
        raise Exception("reportlab is not installed") from e

    buffer = BytesIO()
    
    # Register Korean font
    try:
        font_path = "C:\\Windows\\Fonts\\malgun.ttf"
        if Path(font_path).exists():
            pdfmetrics.registerFont(TTFont("Korean", font_path))
            pdfmetrics.registerFont(TTFont("KoreanBold", font_path))
            title_font = "Korean"
            body_font = "Korean"
    except Exception as e:
        print(f"[WARN] Failed to register Korean font: {e}")
        title_font = "Helvetica"
        body_font = "Helvetica"

    # Create PDF document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm,
    )

    # Create styles
    styles = getSampleStyleSheet()
    
    # Title style
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontName=title_font,
        fontSize=14,
        textColor='black',
        spaceAfter=12,
        alignment=0,
    )
    
    # Body style
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontName=body_font,
        fontSize=9,
        leading=11,
        alignment=0,
    )

    # Build content
    story = []
    
    # Add title
    story.append(Paragraph(report_title, title_style))
    story.append(Spacer(1, 12))
    
    # Add body text - split by paragraphs
    for paragraph in report_text.split("\n"):
        if not paragraph.strip():
            story.append(Spacer(1, 6))
        else:
            story.append(Paragraph(paragraph, body_style))
            story.append(Spacer(1, 4))

    # Build PDF
    try:
        doc.build(story)
    except Exception as e:
        print(f"[WARN] PDF build error: {e}")
    
    buffer.seek(0)
    return buffer.read()
