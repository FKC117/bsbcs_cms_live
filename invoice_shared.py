import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, Table, TableStyle

ORG_SUBTITLE = 'Bangladesh Society for Breast Cancer Study'
INVOICE_BORDER = colors.HexColor('#dce3ec')
INVOICE_GRID = colors.HexColor('#e8edf4')
INVOICE_TEXT = colors.HexColor('#102033')
INVOICE_MUTED = colors.HexColor('#5f6b7a')
INVOICE_ACCENT = colors.HexColor('#1565c0')
INVOICE_HEADER_BG = colors.HexColor('#102033')
INVOICE_CARD_BG = colors.HexColor('#f8fafc')
INVOICE_HIGHLIGHT_BG = colors.HexColor('#eff6ff')


def format_bdt(amount):
    amount = amount or 0
    return f"BDT {float(amount):,.2f}"


def build_invoice_styles():
    styles = getSampleStyleSheet()
    additions = {
        'InvoiceTitle': ParagraphStyle(
            name='InvoiceTitle',
            parent=styles['Title'],
            fontName='Helvetica-Bold',
            fontSize=19,
            leading=23,
            spaceAfter=8,
            textColor=INVOICE_TEXT,
        ),
        'BrandName': ParagraphStyle(
            name='BrandName',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=14,
            leading=17,
            textColor=INVOICE_ACCENT,
        ),
        'SmallMuted': ParagraphStyle(
            name='SmallMuted',
            parent=styles['Normal'],
            fontSize=9,
            leading=12,
            textColor=INVOICE_MUTED,
        ),
        'SmallMutedCenter': ParagraphStyle(
            name='SmallMutedCenter',
            parent=styles['Normal'],
            alignment=TA_CENTER,
            fontSize=8,
            leading=10,
            textColor=INVOICE_MUTED,
        ),
        'BodyCell': ParagraphStyle(
            name='BodyCell',
            parent=styles['Normal'],
            fontSize=10,
            leading=13,
            textColor=INVOICE_TEXT,
        ),
        'BodyCellRight': ParagraphStyle(
            name='BodyCellRight',
            parent=styles['Normal'],
            alignment=TA_RIGHT,
            fontSize=10,
            leading=13,
            textColor=INVOICE_TEXT,
        ),
        'TableHeader': ParagraphStyle(
            name='TableHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=11,
            textColor=colors.white,
        ),
        'RightTotal': ParagraphStyle(
            name='RightTotal',
            parent=styles['Normal'],
            alignment=TA_RIGHT,
            fontName='Helvetica-Bold',
            fontSize=14,
            leading=17,
            textColor=INVOICE_TEXT,
        ),
    }
    for name, style in additions.items():
        if name not in styles.byName:
            styles.add(style)
    return styles


def _status_palette(status_text):
    normalized = (status_text or '').strip().lower()
    if normalized in {'paid', 'completed', 'active'}:
        return colors.HexColor('#15803d'), colors.HexColor('#dcfce7')
    if normalized in {'failed', 'cancelled', 'rejected'}:
        return colors.HexColor('#b91c1c'), colors.HexColor('#fee2e2')
    return colors.HexColor('#b45309'), colors.HexColor('#fef3c7')


def build_brand_cell(styles, logo_path=None, org_name='BSBCS', subtitle=ORG_SUBTITLE):
    brand_text = Paragraph(
        f"<b>{escape(str(org_name))}</b><br/><font size='9'>{escape(str(subtitle))}</font>",
        styles['BrandName'],
    )
    if logo_path and os.path.exists(logo_path):
        reader = ImageReader(logo_path)
        original_width, original_height = reader.getSize()
        max_width = 1.55 * inch
        max_height = 0.82 * inch
        scale = min(max_width / float(original_width), max_height / float(original_height))
        logo_image = Image(
            logo_path,
            width=float(original_width) * scale,
            height=float(original_height) * scale,
        )
        logo_table = Table([[logo_image]], colWidths=[170])
        logo_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        return logo_table
    return brand_text


def build_status_badge(styles, status_text):
    status_color, status_background = _status_palette(status_text)
    badge_style = ParagraphStyle(
        name=f"InvoiceStatusBadge_{status_text}",
        parent=styles['Normal'],
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=13,
        textColor=status_color,
    )
    badge = Table([[Paragraph(escape(str(status_text).upper()), badge_style)]], colWidths=[96], rowHeights=[28])
    badge.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), status_background),
        ('TEXTCOLOR', (0, 0), (-1, -1), status_color),
        ('BOX', (0, 0), (-1, -1), 0.75, status_color),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return badge


def build_invoice_header(styles, logo_path, document_label, invoice_number, status_text, org_name='BSBCS', subtitle=ORG_SUBTITLE, metadata_lines=None):
    metadata = [
        f"<b>{escape(str(document_label))}</b>",
        f"<font size='9'>Invoice: {escape(str(invoice_number or '-'))}</font>",
        f"<font size='9'>Status: {escape(str(status_text or '-'))}</font>",
    ]
    for line in metadata_lines or []:
        if line:
            metadata.append(f"<font size='9'>{escape(str(line))}</font>")

    header_table = Table([
        [
            build_brand_cell(styles, logo_path, org_name=org_name, subtitle=subtitle),
            Paragraph('<br/>'.join(metadata), styles['Normal']),
            build_status_badge(styles, status_text or 'pending'),
        ]
    ], colWidths=[190, 230, 100])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 0), (-1, -1), 1, INVOICE_BORDER),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
    ]))
    return header_table


def build_invoice_title_block(styles, title, subtitle=None):
    rows = [[Paragraph(escape(str(title)), styles['InvoiceTitle'])]]
    if subtitle:
        rows.append([Paragraph(escape(str(subtitle)), styles['SmallMuted'])])
    block = Table(rows, colWidths=[520])
    block.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return block


def build_info_table(styles, left_title, left_lines, right_title, right_lines, col_widths=(250, 250)):
    def card(title, lines):
        content = [f"<b>{escape(str(title))}</b>"]
        for line in lines:
            if line in (None, ''):
                continue
            content.append(escape(str(line)))
        return Paragraph('<br/>'.join(content), styles['Normal'])

    table = Table([[card(left_title, left_lines), card(right_title, right_lines)]], colWidths=list(col_widths))
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), INVOICE_CARD_BG),
        ('BOX', (0, 0), (-1, -1), 0.75, INVOICE_BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.75, INVOICE_BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    return table


def build_line_items_table(styles, headers, rows, col_widths, repeat_rows=1):
    header_row = [Paragraph(f"<b>{escape(str(header))}</b>", styles['TableHeader']) for header in headers]
    data = [header_row] + rows
    table = Table(data, colWidths=list(col_widths), repeatRows=repeat_rows)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), INVOICE_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, INVOICE_CARD_BG]),
        ('BOX', (0, 0), (-1, -1), 0.75, INVOICE_BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, INVOICE_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return table


def build_total_block(styles, label, amount_text):
    total_table = Table(
        [[Paragraph(escape(str(label)), styles['SmallMuted']), Paragraph(escape(str(amount_text)), styles['RightTotal'])]],
        colWidths=[360, 160],
    )
    total_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), INVOICE_HIGHLIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#bfdbfe')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    return total_table


def build_footer_block(styles, footer_text, qr_path=None, qr_caption_lines=None, qr_size=1.35 * inch):
    footer_paragraph = Paragraph(escape(str(footer_text)), styles['SmallMuted'])
    if not qr_path:
        return footer_paragraph

    caption_lines = [line for line in (qr_caption_lines or []) if line]
    qr_elements = [Image(qr_path, width=qr_size, height=qr_size)]
    for line in caption_lines:
        qr_elements.append(Paragraph(escape(str(line)), styles['SmallMutedCenter']))
    qr_table = Table([[item] for item in qr_elements], colWidths=[qr_size + 18])
    qr_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))

    footer_table = Table([[footer_paragraph, qr_table]], colWidths=[360, 120], hAlign='LEFT')
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return footer_table
