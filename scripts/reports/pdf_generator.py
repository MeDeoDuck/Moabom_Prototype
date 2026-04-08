"""
PDF report generation service
"""
from io import BytesIO
from pathlib import Path
from scripts.utils.markdown_renderer import parse_markdown_for_pdf


def render_report_pdf(report_title: str, report_text: str) -> bytes:
    """Render report text (markdown) into a downloadable PDF with Korean support and proper formatting."""
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
    
    # Title style (for main report title)
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontName=title_font,
        fontSize=14,
        textColor='black',
        spaceAfter=12,
        alignment=0,
    )
    
    # H1 style
    h1_style = ParagraphStyle(
        'CustomH1',
        parent=styles['Heading1'],
        fontName=title_font,
        fontSize=13,
        textColor='black',
        spaceAfter=10,
        spaceBefore=10,
        alignment=0,
    )
    
    # H2 style
    h2_style = ParagraphStyle(
        'CustomH2',
        parent=styles['Heading2'],
        fontName=title_font,
        fontSize=11,
        textColor='black',
        spaceAfter=8,
        spaceBefore=8,
        alignment=0,
    )
    
    # H3 style
    h3_style = ParagraphStyle(
        'CustomH3',
        parent=styles['Heading3'],
        fontName=title_font,
        fontSize=10,
        textColor='black',
        spaceAfter=6,
        spaceBefore=6,
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
    
    # Bullet style
    bullet_style = ParagraphStyle(
        'CustomBullet',
        parent=styles['Normal'],
        fontName=body_font,
        fontSize=9,
        leading=11,
        leftIndent=15,
        bulletIndent=5,
        alignment=0,
    )

    # Build content
    story = []
    
    # Add main title
    story.append(Paragraph(report_title, title_style))
    story.append(Spacer(1, 12))
    
    # Parse markdown and add styled content
    parsed_content = parse_markdown_for_pdf(report_text)
    
    for style_type, content in parsed_content:
        if style_type == 'blank':
            story.append(Spacer(1, 6))
        elif style_type == 'h1':
            story.append(Paragraph(content, h1_style))
        elif style_type == 'h2':
            story.append(Paragraph(content, h2_style))
        elif style_type == 'h3':
            story.append(Paragraph(content, h3_style))
        elif style_type == 'bullet':
            story.append(Paragraph(f'• {content}', bullet_style))
        else:  # body
            story.append(Paragraph(content, body_style))
            story.append(Spacer(1, 4))

    # Build PDF
    try:
        doc.build(story)
    except Exception as e:
        print(f"[WARN] PDF build error: {e}")
    
    buffer.seek(0)
    return buffer.read()
