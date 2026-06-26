from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, TableStyle, Table
from io import BytesIO
import os
from reportlab.pdfgen import canvas


def generate_abstract_pdf(event, abstracts):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()

    # Create a justified paragraph style
    justified_style = ParagraphStyle(name='Justified', parent=styles['Normal'], alignment=4)  # Justify text

    elements = []

    # Define the Header
    header = Paragraph(f"Abstracts of {event.name} {event.year}", styles['Title'])
    elements.append(header)
    elements.append(Spacer(1, 24))

    for abstract in abstracts:
        elements.append(Paragraph(f"<b>ID:</b> {abstract.id}", justified_style))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f"<b>Title:</b> {abstract.title}", justified_style))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f"<b>Authors:</b> {abstract.authors}", justified_style))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f"<b>Institution:</b> {abstract.institution}", justified_style))
        elements.append(Spacer(1, 12))

        # Combine heading and text in a single justified paragraph
        elements.append(Paragraph("<b>Introduction:</b> " + abstract.introduction.replace('\n', '<br />'), justified_style))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph("<b>Methods:</b> " + abstract.methods.replace('\n', '<br />'), justified_style))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph("<b>Results:</b> " + abstract.results.replace('\n', '<br />'), justified_style))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph("<b>Conclusion:</b> " + abstract.conclusion.replace('\n', '<br />'), justified_style))
        elements.append(Spacer(1, 12))

        # Add image if available and resize it
        if abstract.image:
            img = Image(abstract.image.path)
            img._restrictSize(5*inch, 5*inch)  # Resize image to fit within 5x5 inches
            elements.append(img)
            elements.append(Spacer(1, 12))

        # Add approval status
        if abstract.approved_for_presentation:
            elements.append(Paragraph("<b>Status:</b> Approved for Presentation", justified_style))
        elif abstract.approved_for_poster:
            elements.append(Paragraph("<b>Status:</b> Approved for Poster", justified_style))
        else:
            elements.append(Paragraph("<b>Status:</b> Not Approved", justified_style))

        elements.append(Spacer(1, 24))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# Abstract Generation in pdf generator end ----------------------------------------------------------------#

# Schedule Generation in pdf generator start ----------------------------------------------------------------#

def generate_schedule_pdf(event, schedules):
    custom_paper_size = (11 * inch, 17 * inch)
    buffer = BytesIO()
    site_logo_path = _get_site_invoice_logo_path()
    event_logo_path = None
    if getattr(event, 'event_logo', None) and getattr(event.event_logo, 'name', None):
        event_logo_path = event.event_logo.path

    doc = SimpleDocTemplate(buffer, pagesize=landscape(custom_paper_size),
                            rightMargin=0.5 * inch, leftMargin=0.5 * inch,
                            topMargin=1.25 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'PDFTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#111827'),
    )
    subtitle_style = ParagraphStyle(
        'PDFSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#6b7280'),
    )
    label_style = ParagraphStyle(
        'PDFLabel',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#6b7280'),
    )
    bold_style = ParagraphStyle(
        'PDFBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=12,
        textColor=colors.HexColor('#111827'),
    )
    small_style = ParagraphStyle(
        'PDFSmall',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#374151'),
    )
    accent = colors.HexColor('#be185d')
    note_color = colors.HexColor('#fde2f0')

    elements = []
    logo_cell = None
    if site_logo_path and os.path.exists(site_logo_path):
        logo_cell = site_logo_path

    event_logo_cell = None
    if event_logo_path and os.path.exists(event_logo_path):
        event_logo_cell = event_logo_path

    def draw_schedule_header(canvas_obj, doc_obj):
        canvas_obj.saveState()
        width, height = doc_obj.pagesize
        y = height - 1.05 * inch

        left_logo_x = doc_obj.leftMargin
        right_logo_x = width - doc_obj.rightMargin - 1.0 * inch
        middle_x = left_logo_x + 1.1 * inch
        card_width = right_logo_x - middle_x - 0.1 * inch
        card_height = 0.55 * inch
        card_y = y + 0.15 * inch

        if logo_cell:
            canvas_obj.drawImage(
                logo_cell,
                left_logo_x,
                y,
                width=1.0 * inch,
                height=1.0 * inch,
                preserveAspectRatio=True,
                mask='auto'
            )

        if event_logo_cell:
            canvas_obj.drawImage(
                event_logo_cell,
                right_logo_x,
                y,
                width=1.0 * inch,
                height=1.0 * inch,
                preserveAspectRatio=True,
                mask='auto'
            )

        canvas_obj.setFillColor(colors.HexColor('#fff1f2'))
        canvas_obj.roundRect(
            middle_x,
            card_y,
            card_width,
            card_height,
            radius=8,
            fill=1,
            stroke=0,
        )
        canvas_obj.setStrokeColor(colors.HexColor('#fbcfe8'))
        canvas_obj.roundRect(
            middle_x,
            card_y,
            card_width,
            card_height,
            radius=8,
            fill=0,
            stroke=1,
        )

        canvas_obj.setFillColor(colors.HexColor('#111827'))
        canvas_obj.setFont('Helvetica-Bold', 11)
        canvas_obj.drawCentredString(
            middle_x + card_width / 2,
            card_y + card_height - 0.18 * inch,
            f"{event.name} {event.year}"
        )
        canvas_obj.setFont('Helvetica', 9)
        canvas_obj.setFillColor(colors.HexColor('#6b7280'))
        canvas_obj.drawCentredString(
            middle_x + card_width / 2,
            card_y + 0.16 * inch,
            'Scientific Program Schedule'
        )
        canvas_obj.restoreState()
        draw_schedule_footer(canvas_obj, doc_obj)

    def draw_schedule_footer(canvas_obj, doc_obj):
        canvas_obj.saveState()
        width, _height = doc_obj.pagesize
        canvas_obj.setFont("Helvetica", 8)
        canvas_obj.setFillColor(colors.HexColor("#6b7280"))
        canvas_obj.drawCentredString(
            width / 2,
            18,
            f"Page {doc_obj.page}"
        )
        canvas_obj.restoreState()

    from .models import TimeSlot, ProgramSession
    from collections import defaultdict

    time_slots = TimeSlot.objects.filter(event=event).select_related('program_day', 'hall_room').order_by('program_day__date', 'start_time', 'hall_room__name')
    program_sessions = ProgramSession.objects.filter(event=event).select_related('program_day', 'hall_room', 'time_slot').prefetch_related('faculty_roles__person', 'items__faculty_roles__person')

    slots_by_day = defaultdict(list)
    for slot in time_slots:
        slots_by_day[slot.program_day_id].append(slot)

    sessions_by_slot = defaultdict(list)
    sessions_by_time_window = defaultdict(list)
    unassigned_sessions_by_day = defaultdict(list)

    for s in program_sessions:
        if s.time_slot_id:
            sessions_by_slot[s.time_slot_id].append(s)
        elif s.program_day_id:
            unassigned_sessions_by_day[s.program_day_id].append(s)
        time_window = (s.program_day_id, s.start_time, s.end_time)
        sessions_by_time_window[time_window].append(s)

    from reportlab.lib.enums import TA_LEFT
    time_label_style = ParagraphStyle('TimeLabel', parent=styles['Normal'], fontSize=9, leading=11, textColor=colors.HexColor('#6b7280'))
    session_title_style = ParagraphStyle('SessionTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=13, textColor=colors.HexColor('#111827'))
    section_text_style = ParagraphStyle('SectionText', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#374151'))

    def session_row(session):
        time_text = f"{session.start_time.strftime('%I:%M %p')} — {session.end_time.strftime('%I:%M %p')}"
        left = Paragraph(f"<b>{time_text}</b><br/><font size=8>{session.hall_room.name if session.hall_room else ''}</font>", time_label_style)

        time_window = (session.program_day_id, session.start_time, session.end_time)
        parallel_count = len(sessions_by_time_window.get(time_window, []))
        badge_html = ''
        if parallel_count > 1:
            badge_html = f"<font color='#be185d'><b>PARALLEL ({parallel_count})</b></font><br/>"

        content_parts = [Paragraph(f"{badge_html}<b>{session.title}</b>", session_title_style)]
        if getattr(session, 'description', None):
            content_parts.append(Paragraph(session.description, section_text_style))

        try:
            role_groups = {}
            for role in session.faculty_roles.all():
                label = role.get_role_display()
                role_groups.setdefault(label, []).append(role.person.name)
            if role_groups:
                grouped_lines = []
                for label, names in role_groups.items():
                    grouped_lines.append(f"<b>{label}</b>: {', '.join(sorted(dict.fromkeys(names)))}")
                content_parts.append(Paragraph('<br/>'.join(grouped_lines), section_text_style))
        except Exception:
            pass

        try:
            for item in session.items.all():
                item_title = getattr(item, 'display_title', None) or getattr(item, 'title', '')
                item_text = f"<b>{item_title}</b>"
                if getattr(item, 'start_time', None) and getattr(item, 'end_time', None):
                    item_text += f" <font color='#6b7280'>({item.start_time.strftime('%I:%M %p')} - {item.end_time.strftime('%I:%M %p')})</font>"
                content_parts.append(Paragraph(item_text, section_text_style))
                try:
                    speakers = [r.person.name for r in item.faculty_roles.all() if r.role == getattr(r, 'ROLE_SPEAKER', 'speaker')]
                    presenters = [r.person.name for r in item.faculty_roles.all() if r.role == getattr(r, 'ROLE_PRESENTER', 'presenter')]
                    if speakers:
                        content_parts.append(Paragraph(f"Speakers: {', '.join(speakers)}", section_text_style))
                    elif presenters:
                        content_parts.append(Paragraph(f"Presenters: {', '.join(presenters)}", section_text_style))
                except Exception:
                    pass
        except Exception:
            pass

        right = content_parts
        tbl = Table([[left, right]], colWidths=[2.2 * inch, 13.8 * inch])
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.white),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#fbcfe8')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        return tbl

    def slot_row(slot):
        label = slot.label or slot.get_slot_type_display()
        time_text = f"{slot.start_time.strftime('%I:%M %p')} — {slot.end_time.strftime('%I:%M %p')}"
        left = Paragraph(f"<b>{time_text}</b><br/><font size=8>{slot.hall_room.name}</font>", time_label_style)
        right = Paragraph(f"<b>{label}</b>", section_text_style)
        color_map = {
            'tea_break': colors.HexColor('#fef3c7'),
            'lunch': colors.HexColor('#d1fae5'),
            'dinner': colors.HexColor('#ede9fe'),
            'ceremony': colors.HexColor('#dbeafe'),
            'custom': colors.HexColor('#f3f4f6'),
            'session': colors.white,
        }
        bg = color_map.get(slot.slot_type, colors.HexColor('#f3f4f6'))
        tbl = Table([[left, right]], colWidths=[2.2 * inch, 13.8 * inch])
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), bg),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        return tbl

    days = []
    from registration.models import ProgramDay
    pd_qs = ProgramDay.objects.filter(event=event).order_by('date', 'name')
    for pd in pd_qs:
        days.append(pd)

    for day_index, day in enumerate(days):
        day_header = Table([[Paragraph(f"<b>{day.name} - {day.date.strftime('%A, %B %d, %Y')}</b>", bold_style)]], colWidths=[16 * inch])
        day_header.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), accent),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(day_header)
        elements.append(Spacer(1, 8))

        day_flowables = []

        for slot in sorted(slots_by_day.get(day.id, []), key=lambda s: (s.start_time, s.hall_room.name if s.hall_room else '')):
            if slot.slot_type == TimeSlot.SLOT_SESSION:
                for s in sessions_by_slot.get(slot.id, []):
                    day_flowables.append(session_row(s))
            else:
                day_flowables.append(slot_row(slot))

        for s in unassigned_sessions_by_day.get(day.id, []):
            day_flowables.append(session_row(s))

        for i, flowable in enumerate(day_flowables):
            elements.append(flowable)
            if i < len(day_flowables) - 1:
                elements.append(Spacer(1, 8))

        if day_index < len(days) - 1:
            elements.append(Spacer(1, 12))

    doc.build(
        elements,
        onFirstPage=draw_schedule_header,
        onLaterPages=draw_schedule_header,
    )
    buffer.seek(0)
    return buffer

# Schedule Generation in pdf generator end ----------------------------------------------------------------

# Invoice Generation in pdf generator start ----------------------------------------------------------------
import os
from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, inch
from reportlab.platypus import Table, TableStyle
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_RIGHT
from invoice_shared import build_footer_block, build_info_table, build_invoice_header, build_invoice_styles, build_invoice_title_block, build_line_items_table, build_total_block

def generate_invoice(participant, event, payment_status):
    from .qr_utils import ensure_registration_qr

    invoice_amount = payment_status.amount or 0
    qr_path = ensure_registration_qr(payment_status)
    if not (qr_path and os.path.exists(qr_path)):
        qr_path = None

    file_name = f"invoice_{payment_status.id}.pdf"
    invoices_dir = os.path.join(settings.MEDIA_ROOT, 'invoices')
    os.makedirs(invoices_dir, exist_ok=True)
    file_path = os.path.join(invoices_dir, file_name)

    status_text = payment_status.get_status_display() if hasattr(payment_status, 'get_status_display') else str(payment_status.status).title()
    branding = _get_site_invoice_branding(prefer_membership_logo=False)
    logo_path = branding['logo_path']
    styles = build_invoice_styles()
    event_date = event.start_date.strftime('%B %d, %Y') if getattr(event, 'start_date', None) else '-'
    invoice_dt = timezone.localtime(timezone.now())
    invoice_date = invoice_dt.strftime('%B %d, %Y')
    invoice_time = invoice_dt.strftime('%I:%M %p')

    doc = SimpleDocTemplate(
        file_path,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=42,
        bottomMargin=42,
    )

    rows = [[
        Paragraph(f"Registration fees for {event.name} {event.year}", styles['BodyCell']),
        Paragraph("1", styles['BodyCell']),
        Paragraph(_format_bdt(invoice_amount), styles['BodyCellRight']),
        Paragraph(_format_bdt(invoice_amount), styles['BodyCellRight']),
    ]]

    elements = [
        build_invoice_header(
            styles,
            logo_path,
            "Registration Invoice",
            payment_status.merchant_invoice_number,
            status_text,
            org_name=branding['org_name'],
            subtitle=branding['subtitle'],
            metadata_lines=[f'Invoice date: {invoice_date}', f'Generated at: {invoice_time}'],
        ),
        Spacer(1, 18),
        build_invoice_title_block(styles, 'Event Registration Invoice', 'Registration invoice for a single event participant.'),
        Spacer(1, 10),
        build_info_table(
            styles,
            "Bill To",
            [participant.name, getattr(participant, 'email', ''), getattr(participant, 'phone', '')],
            "Event",
            [f"{event.name} {event.year}", event_date, event.location or '', f"Invoice amount: {_format_bdt(invoice_amount)}"],
        ),
        Spacer(1, 18),
        build_line_items_table(styles, ["Description", "Quantity", "Unit Price", "Total"], rows, [250, 80, 90, 90]),
        Spacer(1, 16),
        build_total_block(styles, 'Total payable', _format_bdt(invoice_amount)),
        Spacer(1, 24),
        build_footer_block(
            styles,
            "This is a computer-generated invoice and does not need any signature.",
            qr_path=qr_path,
            qr_caption_lines=["SCAN AT REGISTRATION DESK", participant.name[:32]],
        ),
    ]
    doc.build(elements)
    return file_path

# Invoice Generation End ----------------------------------------------------------------


def _format_bdt(amount):
    amount = amount or 0
    return f"BDT {float(amount):,.2f}"


def _get_site_invoice_branding(prefer_membership_logo=True):
    branding = {
        'logo_path': None,
        'org_name': 'BSBCS',
        'subtitle': 'Bangladesh Society for Breast Cancer Study',
    }
    try:
        from website.models import SiteSettings

        site_settings = SiteSettings.objects.first()
        if not site_settings:
            return branding

        abbreviation = (site_settings.abbreviation or '').strip()
        site_name = (site_settings.site_name or '').strip()
        tag_line = (site_settings.tag_line or '').strip()

        if abbreviation:
            branding['org_name'] = abbreviation
        elif site_name:
            branding['org_name'] = site_name

        if site_name and abbreviation and site_name.lower() != abbreviation.lower():
            branding['subtitle'] = site_name
        elif tag_line:
            branding['subtitle'] = tag_line
        elif site_name:
            branding['subtitle'] = site_name

        logo = None
        if prefer_membership_logo:
            logo = site_settings.membership_invoice_logo or site_settings.logo
        else:
            logo = site_settings.logo or site_settings.membership_invoice_logo
        if logo and os.path.exists(logo.path):
            branding['logo_path'] = logo.path
    except Exception:
        return branding
    return branding


def generate_corporate_invoice(corporate_payment):
    from .qr_utils import ensure_registration_qr
    from .models import PaymentStatus

    event = corporate_payment.event
    account = corporate_payment.corporate_account
    file_name = f"corporate_invoice_{corporate_payment.id}.pdf"
    invoices_dir = os.path.join(settings.MEDIA_ROOT, 'media', 'corporate_invoices')
    os.makedirs(invoices_dir, exist_ok=True)
    file_path = os.path.join(invoices_dir, file_name)

    styles = build_invoice_styles()
    branding = _get_site_invoice_branding(prefer_membership_logo=False)
    logo_path = branding['logo_path']
    status_text = corporate_payment.get_status_display() if hasattr(corporate_payment, 'get_status_display') else str(corporate_payment.status).title()
    event_date = event.start_date.strftime('%B %d, %Y') if getattr(event, 'start_date', None) else '-'
    invoice_dt = timezone.localtime(timezone.now())
    invoice_date = invoice_dt.strftime('%B %d, %Y')
    invoice_time = invoice_dt.strftime('%I:%M %p')
    attendees = list(corporate_payment.attendees.select_related('participant', 'matched_user').all())

    doc = SimpleDocTemplate(
        file_path,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=42,
        bottomMargin=42,
    )

    attendee_rows = []
    for attendee in attendees:
        amount = attendee.participant.get_payable_amount() if attendee.participant else 0
        attendee_rows.append([
            Paragraph(attendee.name or '-', styles['BodyCell']),
            Paragraph('<br/>'.join([value for value in [attendee.email, attendee.phone] if value]), styles['SmallMuted']),
            Paragraph(attendee.applied_fee_label, styles['SmallMuted']),
            Paragraph(_format_bdt(amount), styles['BodyCellRight']),
        ])

    if not attendee_rows:
        attendee_rows.append([
            Paragraph('Corporate event registration', styles['BodyCell']),
            Paragraph('-', styles['SmallMuted']),
            Paragraph('Summary invoice', styles['SmallMuted']),
            Paragraph(_format_bdt(corporate_payment.amount), styles['BodyCellRight']),
        ])


    bill_to_lines = [account.company_name, account.contact_name]
    if getattr(account, 'contact_designation', None):
        bill_to_lines.append(account.contact_designation)
    bill_to_lines.extend([account.email, account.phone])

    elements = [
        build_invoice_header(
            styles,
            logo_path,
            'Corporate Invoice',
            corporate_payment.merchant_invoice_number,
            status_text,
            org_name=branding['org_name'],
            subtitle=branding['subtitle'],
            metadata_lines=[f'Invoice date: {invoice_date}', f'Generated at: {invoice_time}'],
        ),
        Spacer(1, 18),
        build_invoice_title_block(styles, 'Corporate Event Registration Invoice', 'Grouped billing summary for approved corporate attendees.'),
        Spacer(1, 10),
        build_info_table(
            styles,
            'Bill To',
            bill_to_lines,
            'Event',
            [f'{event.name} {event.year}', event_date, event.location or '', f'Included attendees: {len(attendees)}'],
        ),
        Spacer(1, 18),
        build_line_items_table(styles, ['Attendee', 'Contact', 'Fee category', 'Amount'], attendee_rows, [160, 150, 130, 80]),
        Spacer(1, 16),
        build_total_block(styles, 'Total payable', _format_bdt(corporate_payment.amount)),
        Spacer(1, 24),
        build_footer_block(
            styles,
            'This is a computer-generated invoice and does not need any signature.',
        ),
    ]

    doc.build(elements)
    corporate_payment.invoice.name = f'media/corporate_invoices/{file_name}'
    corporate_payment.save(update_fields=['invoice', 'updated_at'])
    return file_path



def generate_feedback_report_pdf(event, report_data, site_settings=None):
    from datetime import datetime
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.55 * inch,
    )
    styles = getSampleStyleSheet()
    organizer_name = ''
    if site_settings and getattr(site_settings, 'site_name', None):
        organizer_name = site_settings.site_name
    elif site_settings and getattr(site_settings, 'abbreviation', None):
        organizer_name = site_settings.abbreviation
    else:
        organizer_name = 'BSBCS'

    event_title_text = f"{event.name} {event.year}".strip()
    title_length = len(event_title_text)
    compact_title_mode = title_length > 32
    extra_compact_title_mode = title_length > 48

    title_font_size = 22
    title_leading = 26
    subtitle_font_size = 10
    subtitle_leading = 14
    meta_font_size = 8.5
    meta_leading = 11
    logo_size = 0.86 * inch
    header_title_width = 5.0 * inch
    header_meta_width = 3.15 * inch
    executive_spacing_after_header = 10
    executive_spacing_after_summary = 10
    executive_subtitle_text = 'A board-ready event snapshot covering registration health, payment completion, attendance proxy, participation mix, geography, institutions, corporate activity, and abstract outcomes.'

    if compact_title_mode:
        title_font_size = 20
        title_leading = 23
        subtitle_font_size = 9
        subtitle_leading = 12
        meta_font_size = 8
        meta_leading = 10
        logo_size = 0.78 * inch
        header_title_width = 5.45 * inch
        header_meta_width = 2.7 * inch
        executive_spacing_after_header = 8
        executive_spacing_after_summary = 8
        executive_subtitle_text = 'A board-ready event snapshot across registrations, payments, attendance proxy, participation mix, geography, institutions, corporate activity, and abstracts.'

    if extra_compact_title_mode:
        title_font_size = 18
        title_leading = 21
        subtitle_font_size = 8.5
        subtitle_leading = 11
        meta_font_size = 7.5
        meta_leading = 9
        logo_size = 0.7 * inch
        header_title_width = 5.8 * inch
        header_meta_width = 2.35 * inch
        executive_subtitle_text = 'A board-ready event snapshot across registrations, payments, attendance, geography, institutions, corporate activity, and abstracts.'

    title_style = ParagraphStyle(
        'FeedbackPDFTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=colors.HexColor('#0f172a'),
        spaceAfter=6,
    )
    section_kicker_style = ParagraphStyle(
        'FeedbackPDFKicker',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#0f8aa8'),
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        'FeedbackPDFSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#475569'),
    )
    card_value_style = ParagraphStyle(
        'FeedbackPDFCardValue',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0f172a'),
        alignment=TA_CENTER,
    )
    card_label_style = ParagraphStyle(
        'FeedbackPDFCardLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#64748b'),
        alignment=TA_CENTER,
    )
    body_style = ParagraphStyle(
        'FeedbackPDFBody',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#334155'),
    )
    answer_style = ParagraphStyle(
        'FeedbackPDFAnswer',
        parent=styles['Normal'],
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#334155'),
    )
    table_head_style = ParagraphStyle(
        'FeedbackPDFTableHead',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    table_cell_style = ParagraphStyle(
        'FeedbackPDFTableCell',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1e293b'),
        alignment=TA_CENTER,
    )
    appendix_cell_style = ParagraphStyle(
        'FeedbackPDFApxCell',
        parent=styles['Normal'],
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor('#334155'),
    )
    appendix_head_style = ParagraphStyle(
        'FeedbackPDFApxHead',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    right_meta_style = ParagraphStyle(
        'FeedbackPDFRightMeta',
        parent=styles['Normal'],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#475569'),
        alignment=TA_RIGHT,
    )
    question_title_style = ParagraphStyle(
        'FeedbackPDFQuestionTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0f172a'),
    )

    def format_event_date_range():
        start = getattr(event, 'start_date', None)
        end = getattr(event, 'end_date', None)
        if start and end:
            if start == end:
                return start.strftime('%d %B %Y')
            if start.year == end.year and start.month == end.month:
                return f"{start.strftime('%d')} - {end.strftime('%d %B %Y')}"
            if start.year == end.year:
                return f"{start.strftime('%d %B')} - {end.strftime('%d %B %Y')}"
            return f"{start.strftime('%d %B %Y')} - {end.strftime('%d %B %Y')}"
        if start:
            return start.strftime('%d %B %Y')
        return 'Date not available'

    def safe_image(path_value, width, height):
        if path_value and os.path.exists(path_value):
            image = Image(path_value, width=width, height=height)
            image.hAlign = 'LEFT'
            return image
        return Spacer(width, height)

    def stat_card(label, value, note, border_color, fill_color, value_color):
        table = Table([
            [Paragraph(label.upper(), card_label_style)],
            [Paragraph(str(value), ParagraphStyle('TmpValue', parent=card_value_style, textColor=value_color))],
            [Paragraph(note, ParagraphStyle('TmpNote', parent=body_style, alignment=TA_CENTER, fontSize=8, leading=10, textColor=colors.HexColor('#64748b')))],
        ], colWidths=[2.7 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), fill_color),
            ('BOX', (0, 0), (-1, -1), 0.8, border_color),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        return table

    def radio_bar_drawing(percent, count, label):
        drawing = Drawing(280, 18)
        drawing.add(Rect(0, 4, 280, 10, rx=5, ry=5, fillColor=colors.HexColor('#e2e8f0'), strokeColor=colors.HexColor('#dbeafe')))
        fill_width = max(8, 280 * (percent / 100.0)) if count else 0
        if fill_width:
            drawing.add(Rect(0, 4, fill_width, 10, rx=5, ry=5, fillColor=colors.HexColor('#2563eb'), strokeColor=colors.HexColor('#2563eb')))
        return drawing

    class FeedbackReportCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.draw_footer(num_pages)
                canvas.Canvas.showPage(self)
            canvas.Canvas.save(self)

        def draw_footer(self, page_count):
            width, _height = landscape(A4)
            self.saveState()
            self.setStrokeColor(colors.HexColor('#dbe4f0'))
            self.line(doc.leftMargin, 24, width - doc.rightMargin, 24)
            self.setFont('Helvetica', 8)
            self.setFillColor(colors.HexColor('#64748b'))
            self.drawString(doc.leftMargin, 12, f"{event.name} {event.year} Feedback report")
            self.drawRightString(width - doc.rightMargin, 12, f"Page {self._pageNumber} of {page_count}")
            self.restoreState()

    logo_path = getattr(getattr(site_settings, 'logo', None), 'path', None) if site_settings and getattr(site_settings, 'logo', None) else None
    event_logo_path = getattr(getattr(event, 'event_logo', None), 'path', None) if getattr(event, 'event_logo', None) else None

    left_logo = safe_image(logo_path, 0.9 * inch, 0.9 * inch)
    right_logo = safe_image(event_logo_path, 0.9 * inch, 0.9 * inch)

    meta_lines = [
        f"<b>Organizer:</b> {organizer_name}",
        f"<b>Event:</b> {event.name} {event.year}",
        f"<b>Date:</b> {format_event_date_range()}",
        f"<b>Location:</b> {getattr(event, 'location', None) or 'Not specified'}",
        f"<b>Generated:</b> {datetime.now().strftime('%d %B %Y, %I:%M %p')}",
    ]

    header_table = Table([
        [
            left_logo,
            [
                Paragraph('FEEDBACK REPORT', section_kicker_style),
                Paragraph(f"{event.name} {event.year}", title_style),
                Paragraph('Participant submissions, question-wise insights, and response appendix prepared for event organizers.', subtitle_style),
            ],
            [
                Paragraph(line, right_meta_style) for line in meta_lines
            ],
            right_logo,
        ]
    ], colWidths=[0.95 * inch, 5.0 * inch, 3.25 * inch, 0.95 * inch])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    totals = report_data.get('totals', {})
    summary_cards = Table([
        [
            stat_card('Participants', totals.get('participants', 0), 'Submitted participants in this filtered report', colors.HexColor('#bfdbfe'), colors.HexColor('#eff6ff'), colors.HexColor('#1d4ed8')),
            stat_card('Submitted', totals.get('submitted', 0), 'Participants included in the report dataset', colors.HexColor('#bbf7d0'), colors.HexColor('#f0fdf4'), colors.HexColor('#15803d')),
            stat_card('Issued kits', totals.get('issued', 0), 'Submitted participants whose kits are already issued', colors.HexColor('#cbd5e1'), colors.HexColor('#f8fafc'), colors.HexColor('#0f172a')),
        ]
    ], colWidths=[2.8 * inch, 2.8 * inch, 2.8 * inch])
    summary_cards.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    elements = [header_table, Spacer(1, 18), summary_cards, Spacer(1, 18)]

    for index, insight in enumerate(report_data.get('insights', []), start=1):
        elements.append(Paragraph(f"QUESTION {index}", section_kicker_style))
        elements.append(Paragraph(insight['question'].question_text or f'Question {index}', question_title_style))
        elements.append(Paragraph(
            f"Type: <b>{insight['question'].get_question_type_display()}</b> &nbsp;&nbsp; | &nbsp;&nbsp; Answered by <b>{insight.get('answered_participants', 0)}/{insight.get('submitted_participants', 0)}</b> submitted participants.",
            body_style,
        ))
        elements.append(Spacer(1, 10))

        if insight.get('kind') == 'radio':
            radio_rows = [[
                Paragraph('Option', table_head_style),
                Paragraph('Count', table_head_style),
                Paragraph('Share', table_head_style),
                Paragraph('Distribution', table_head_style),
            ]]
            for bar in insight.get('bars', []):
                radio_rows.append([
                    Paragraph(bar['label'], body_style),
                    Paragraph(str(bar['count']), table_cell_style),
                    Paragraph(f"{bar['percent']}%", table_cell_style),
                    radio_bar_drawing(bar['percent'], bar['count'], bar['label']),
                ])
            radio_table = Table(radio_rows, colWidths=[2.8 * inch, 0.8 * inch, 0.8 * inch, 3.3 * inch], repeatRows=1)
            radio_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102033')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#dbe4f0')),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5edf6')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fbff')]),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.extend([radio_table, Spacer(1, 16)])

        elif insight.get('kind') == 'matrix':
            matrix_columns = insight.get('matrix_columns', [])
            matrix_data = [[Paragraph('Row', table_head_style)]]
            matrix_data[0].extend([Paragraph(str(column), table_head_style) for column in matrix_columns])
            matrix_data[0].append(Paragraph('Total', table_head_style))
            for row in insight.get('matrix_rows', []):
                row_cells = [Paragraph(row['label'], body_style)]
                for cell in row.get('cells', []):
                    cell_style = ParagraphStyle(
                        'MatrixCellTmp',
                        parent=table_cell_style,
                        textColor=colors.white if cell.get('use_light_text') else colors.HexColor('#1d4ed8'),
                    )
                    row_cells.append(Paragraph(str(cell['count']), cell_style))
                row_cells.append(Paragraph(str(row.get('total', 0)), table_cell_style))
                matrix_data.append(row_cells)
            matrix_table = Table(matrix_data, repeatRows=1)
            matrix_style = [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102033')),
                ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#dbe4f0')),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5edf6')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 7),
                ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('BACKGROUND', (0, 1), (0, -1), colors.white),
                ('BACKGROUND', (-1, 1), (-1, -1), colors.HexColor('#f8fafc')),
            ]
            for row_index, row in enumerate(insight.get('matrix_rows', []), start=1):
                for col_index, cell in enumerate(row.get('cells', []), start=1):
                    if cell.get('intensity'):
                        matrix_style.append(('BACKGROUND', (col_index, row_index), (col_index, row_index), colors.Color(37/255, 99/255, 235/255, alpha=min(cell['intensity'] / 100, 0.95))))
                    else:
                        matrix_style.append(('BACKGROUND', (col_index, row_index), (col_index, row_index), colors.HexColor('#f8fafc')))
            matrix_table.setStyle(TableStyle(matrix_style))
            elements.extend([matrix_table, Spacer(1, 16)])

        else:
            all_text_answers = list(insight.get('text_answers', []))
            longest_text_answers = sorted(all_text_answers, key=lambda answer: (len(answer or ''), answer or ''), reverse=True)[:10]
            elements.append(Paragraph(f"{insight.get('response_count', 0)} text response(s) captured for this question. Showing the 10 longest responses in the PDF summary.", body_style))
            elements.append(Spacer(1, 8))
            text_rows = [[Paragraph('No.', table_head_style), Paragraph('Response', table_head_style)]]
            for answer_index, answer in enumerate(longest_text_answers, start=1):
                text_rows.append([
                    Paragraph(str(answer_index), table_cell_style),
                    Paragraph(answer.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>'), answer_style),
                ])
            if len(text_rows) == 1:
                text_rows.append([Paragraph('-', table_cell_style), Paragraph('No saved text responses yet.', body_style)])
            text_table = Table(text_rows, colWidths=[0.45 * inch, 9.1 * inch], repeatRows=1)
            text_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102033')),
                ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#dbe4f0')),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5edf6')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fbff')]),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 7),
                ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.extend([text_table, Spacer(1, 16)])

    elements.append(PageBreak())
    elements.append(Paragraph('PARTICIPANT APPENDIX', section_kicker_style))
    elements.append(Paragraph('Submitted participant response index', title_style))
    elements.append(Paragraph('This appendix lists submitted participants and their eligibility-related status at the time of export.', subtitle_style))
    elements.append(Spacer(1, 12))

    appendix_rows = [[
        Paragraph('Participant', appendix_head_style),
        Paragraph('Email', appendix_head_style),
        Paragraph('Invoice', appendix_head_style),
        Paragraph('Approved', appendix_head_style),
        Paragraph('Payment', appendix_head_style),
        Paragraph('Kit', appendix_head_style),
        Paragraph('Answered', appendix_head_style),
    ]]
    for row in report_data.get('rows', []):
        appendix_rows.append([
            Paragraph((row['participant'].name or '-').replace('&', '&amp;'), appendix_cell_style),
            Paragraph((row['participant'].email or '-').replace('&', '&amp;'), appendix_cell_style),
            Paragraph((row.get('invoice_number') or '-').replace('&', '&amp;'), appendix_cell_style),
            Paragraph('Yes' if row['participant'].approved else 'No', appendix_cell_style),
            Paragraph(getattr(row.get('payment_status'), 'status', 'Unpaid').title() if row.get('payment_status') else 'Unpaid', appendix_cell_style),
            Paragraph('Issued' if row.get('kit_issued') else 'Not issued', appendix_cell_style),
            Paragraph(f"{row.get('answered_questions', 0)}/{len(report_data.get('questions', []))}", appendix_cell_style),
        ])
    appendix_table = Table(appendix_rows, colWidths=[1.7 * inch, 2.2 * inch, 1.4 * inch, 0.65 * inch, 0.9 * inch, 0.8 * inch, 0.8 * inch], repeatRows=1)
    appendix_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102033')),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#dbe4f0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5edf6')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fbff')]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(appendix_table)

    doc.build(elements, canvasmaker=FeedbackReportCanvas)
    buffer.seek(0)
    return buffer



def generate_event_report_pdf(event, report_data, site_settings=None, feedback_report_data=None):
    from datetime import datetime
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.graphics.shapes import Drawing, Rect
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.68 * inch,
        bottomMargin=0.55 * inch,
    )
    styles = getSampleStyleSheet()

    organizer_name = ''
    if site_settings and getattr(site_settings, 'site_name', None):
        organizer_name = site_settings.site_name
    elif site_settings and getattr(site_settings, 'abbreviation', None):
        organizer_name = site_settings.abbreviation
    else:
        organizer_name = 'BSBCS'

    event_title_text = f"{event.name} {event.year}".strip()
    title_length = len(event_title_text)
    compact_title_mode = title_length > 32
    extra_compact_title_mode = title_length > 48

    title_font_size = 22
    title_leading = 26
    subtitle_font_size = 10
    subtitle_leading = 14
    meta_font_size = 8.5
    meta_leading = 11
    logo_size = 0.86 * inch
    header_title_width = 5.0 * inch
    header_meta_width = 3.15 * inch
    executive_spacing_after_header = 10
    executive_spacing_after_summary = 10
    executive_subtitle_text = 'A board-ready event snapshot covering registration health, payment completion, attendance proxy, participation mix, geography, institutions, corporate activity, and abstract outcomes.'

    if compact_title_mode:
        title_font_size = 20
        title_leading = 23
        subtitle_font_size = 9
        subtitle_leading = 12
        meta_font_size = 8
        meta_leading = 10
        logo_size = 0.78 * inch
        header_title_width = 5.45 * inch
        header_meta_width = 2.7 * inch
        executive_spacing_after_header = 8
        executive_spacing_after_summary = 8
        executive_subtitle_text = 'A board-ready event snapshot across registrations, payments, attendance proxy, participation mix, geography, institutions, corporate activity, and abstracts.'

    if extra_compact_title_mode:
        title_font_size = 18
        title_leading = 21
        subtitle_font_size = 8.5
        subtitle_leading = 11
        meta_font_size = 7.5
        meta_leading = 9
        logo_size = 0.7 * inch
        header_title_width = 5.8 * inch
        header_meta_width = 2.35 * inch
        executive_subtitle_text = 'A board-ready event snapshot across registrations, payments, attendance, geography, institutions, corporate activity, and abstracts.'

    title_style = ParagraphStyle(
        'EventPDFTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=title_font_size,
        leading=title_leading,
        textColor=colors.HexColor('#0f172a'),
        spaceAfter=4 if not compact_title_mode else 3,
    )
    section_kicker_style = ParagraphStyle(
        'EventPDFKicker',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#0f8aa8'),
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        'EventPDFSubtitle',
        parent=styles['Normal'],
        fontSize=subtitle_font_size,
        leading=subtitle_leading,
        textColor=colors.HexColor('#475569'),
    )
    body_style = ParagraphStyle(
        'EventPDFBody',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#334155'),
    )
    muted_style = ParagraphStyle(
        'EventPDFMuted',
        parent=body_style,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#64748b'),
    )
    card_value_style = ParagraphStyle(
        'EventPDFCardValue',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0f172a'),
        alignment=TA_CENTER,
    )
    card_label_style = ParagraphStyle(
        'EventPDFCardLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#64748b'),
        alignment=TA_CENTER,
    )
    metric_label_style = ParagraphStyle(
        'EventPDFMetricLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#64748b'),
    )
    metric_value_style = ParagraphStyle(
        'EventPDFMetricValue',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=16,
        textColor=colors.HexColor('#0f172a'),
    )
    table_head_style = ParagraphStyle(
        'EventPDFTableHead',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    table_cell_style = ParagraphStyle(
        'EventPDFTableCell',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1e293b'),
    )
    right_meta_style = ParagraphStyle(
        'EventPDFRightMeta',
        parent=styles['Normal'],
        fontSize=meta_font_size,
        leading=meta_leading,
        textColor=colors.HexColor('#475569'),
        alignment=TA_RIGHT,
    )
    feedback_question_title_style = ParagraphStyle(
        'EventPDFFeedbackQuestionTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0f172a'),
    )
    feedback_answer_style = ParagraphStyle(
        'EventPDFFeedbackAnswer',
        parent=styles['Normal'],
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#334155'),
    )
    feedback_appendix_cell_style = ParagraphStyle(
        'EventPDFFeedbackAppendixCell',
        parent=styles['Normal'],
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor('#334155'),
    )
    feedback_appendix_head_style = ParagraphStyle(
        'EventPDFFeedbackAppendixHead',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9,
        textColor=colors.white,
        alignment=TA_CENTER,
    )

    overview = report_data.get('overview', {})
    institutions = report_data.get('institutions', [])
    countries = report_data.get('countries', [])
    feedback_report_data = feedback_report_data or {}

    def esc(value):
        if value is None:
            return ''
        return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def format_event_date_range():
        start = getattr(event, 'start_date', None)
        end = getattr(event, 'end_date', None)
        if start and end:
            if start == end:
                return start.strftime('%d %B %Y')
            if start.year == end.year and start.month == end.month:
                return f"{start.strftime('%d')} - {end.strftime('%d %B %Y')}"
            if start.year == end.year:
                return f"{start.strftime('%d %B')} - {end.strftime('%d %B %Y')}"
            return f"{start.strftime('%d %B %Y')} - {end.strftime('%d %B %Y')}"
        if start:
            return start.strftime('%d %B %Y')
        return 'Date not available'

    def safe_image(path_value, width, height):
        if path_value and os.path.exists(path_value):
            image = Image(path_value, width=width, height=height)
            image.hAlign = 'LEFT'
            return image
        return Spacer(width, height)

    def stat_card(label, value, note, border_color, fill_color, value_color):
        table = Table([
            [Paragraph(label.upper(), card_label_style)],
            [Paragraph(esc(value), ParagraphStyle('TmpEventValue', parent=card_value_style, textColor=value_color))],
            [Paragraph(esc(note), ParagraphStyle('TmpEventNote', parent=muted_style, alignment=TA_CENTER))],
        ], colWidths=[2.45 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), fill_color),
            ('BOX', (0, 0), (-1, -1), 0.85, border_color),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        return table

    def metric_panel(title, rows, border_color, fill_color):
        panel_rows = [[Paragraph(title.upper(), ParagraphStyle('TmpMetricHead', parent=metric_label_style, textColor=colors.HexColor('#0f8aa8'))), '', '']]
        for label, value in rows:
            panel_rows.append([Paragraph(esc(label), metric_label_style), Paragraph(esc(value), metric_value_style), ''])
        table = Table(panel_rows, colWidths=[1.6 * inch, 0.9 * inch, 0.01 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), fill_color),
            ('BOX', (0, 0), (-1, -1), 0.8, border_color),
            ('SPAN', (0, 0), (-1, 0)),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LINEBELOW', (0, 1), (-1, -2), 0.35, colors.HexColor('#dbe4f0')),
        ]))
        return table

    def ranked_bar(percent, color_hex):
        drawing = Drawing(180, 14)
        drawing.add(Rect(0, 3, 180, 8, rx=4, ry=4, fillColor=colors.HexColor('#e2e8f0'), strokeColor=colors.HexColor('#e2e8f0')))
        fill_width = max(8, 180 * (percent / 100.0)) if percent else 0
        if fill_width:
            drawing.add(Rect(0, 3, fill_width, 8, rx=4, ry=4, fillColor=colors.HexColor(color_hex), strokeColor=colors.HexColor(color_hex)))
        return drawing

    class EventReportCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            page_count = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.draw_footer(page_count)
                canvas.Canvas.showPage(self)
            canvas.Canvas.save(self)

        def draw_footer(self, page_count):
            width, _height = landscape(A4)
            self.saveState()
            self.setStrokeColor(colors.HexColor('#dbe4f0'))
            self.line(doc.leftMargin, 24, width - doc.rightMargin, 24)
            self.setFont('Helvetica', 8)
            self.setFillColor(colors.HexColor('#64748b'))
            self.drawString(doc.leftMargin, 12, f"{event.name} {event.year} Event report")
            self.drawRightString(width - doc.rightMargin, 12, f"Page {self._pageNumber} of {page_count}")
            self.restoreState()

    logo_path = getattr(getattr(site_settings, 'logo', None), 'path', None) if site_settings and getattr(site_settings, 'logo', None) else None
    event_logo_path = getattr(getattr(event, 'event_logo', None), 'path', None) if getattr(event, 'event_logo', None) else None

    meta_lines = [
        f"<b>Organizer:</b> {esc(organizer_name)}",
        f"<b>Event:</b> {esc(event.name)} {esc(event.year)}",
        f"<b>Date:</b> {esc(format_event_date_range())}",
        f"<b>Location:</b> {esc(getattr(event, 'location', None) or 'Not specified')}",
        f"<b>Status:</b> {esc(getattr(event, 'get_event_status_display', lambda: event.event_status)())} / {esc(getattr(event, 'registration', None) or '-')}",
        f"<b>Generated:</b> {datetime.now().strftime('%d %B %Y, %I:%M %p')}",
    ]

    header_table = Table([[
        safe_image(logo_path, logo_size, logo_size),
        [
            Paragraph('EVENT REPORT', section_kicker_style),
            Paragraph(esc(event_title_text), title_style),
            Paragraph(executive_subtitle_text, subtitle_style),
        ],
        [Paragraph(line, right_meta_style) for line in meta_lines],
        safe_image(event_logo_path, logo_size, logo_size),
    ]], colWidths=[0.95 * inch, header_title_width, header_meta_width, 0.95 * inch])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    summary_cards = Table([[
        stat_card('Registrations started', overview.get('registrations_started', 0), 'All participant rows created for this event', colors.HexColor('#bfdbfe'), colors.HexColor('#eff6ff'), colors.HexColor('#1d4ed8')),
        stat_card('Approved', overview.get('approved', 0), f"Denied {overview.get('denied', 0)} / Pending {overview.get('pending', 0)}", colors.HexColor('#bbf7d0'), colors.HexColor('#f0fdf4'), colors.HexColor('#15803d')),
        stat_card('Attendance proxy', overview.get('attended_count', 0), f"Kit issued rows / {overview.get('attendance_rate', 0)}% of approved", colors.HexColor('#fde68a'), colors.HexColor('#fffbeb'), colors.HexColor('#a16207')),
        stat_card('Total revenue', f"BDT {overview.get('total_revenue', 0):,.0f}", f"Participant BDT {overview.get('participant_revenue', 0):,.0f} / Corporate BDT {overview.get('corporate_revenue', 0):,.0f}", colors.HexColor('#bae6fd'), colors.HexColor('#ecfeff'), colors.HexColor('#0f766e')),
    ]], colWidths=[2.48 * inch, 2.48 * inch, 2.48 * inch, 2.48 * inch])
    summary_cards.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    registration_panel = metric_panel('Registration mix', [
        ('Members', overview.get('member_count', 0)),
        ('Regular', overview.get('regular_count', 0)),
        ('Company person', overview.get('company_person_count', 0)),
        ('Complementary', overview.get('complementary_count', 0)),
        ('Bangladesh', overview.get('bangladesh_count', 0)),
        ('Abroad', overview.get('abroad_count', 0)),
    ], colors.HexColor('#cbd5e1'), colors.HexColor('#f8fafc'))

    payment_panel = metric_panel('Payment pulse', [
        ('Paid / completed', overview.get('participant_paid_count', 0)),
        ('Open / unpaid', overview.get('participant_unpaid_count', 0)),
        ('Failed / cancelled', overview.get('participant_failed_count', 0)),
        ('Participant revenue', f"BDT {overview.get('participant_revenue', 0):,.0f}"),
        ('Corporate revenue', f"BDT {overview.get('corporate_revenue', 0):,.0f}"),
        ('Total revenue', f"BDT {overview.get('total_revenue', 0):,.0f}"),
    ], colors.HexColor('#bae6fd'), colors.HexColor('#f8fdff'))

    corporate_panel = metric_panel('Corporate and abstracts', [
        ('Corporate registrations', overview.get('corporate_registrations', 0)),
        ('Corporate attendees', overview.get('corporate_total_attendees', 0)),
        ('Corporate approved', overview.get('corporate_approved', 0)),
        ('Corporate pending', overview.get('corporate_pending', 0)),
        ('Abstract submitted', overview.get('abstracts_submitted', 0)),
        ('Presentation approved', overview.get('abstracts_presentation', 0)),
        ('Poster approved', overview.get('abstracts_poster', 0)),
        ('Abstract pending', overview.get('abstracts_pending', 0)),
    ], colors.HexColor('#fde68a'), colors.HexColor('#fffdf6'))

    detail_row = Table([[registration_panel, payment_panel, corporate_panel]], colWidths=[3.2 * inch, 3.2 * inch, 3.7 * inch])
    detail_row.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    executive_summary = Paragraph(
        f"<b>Executive summary:</b> {overview.get('approved', 0)} approved participants, {overview.get('participant_paid_count', 0)} paid/completed registrations, {overview.get('attended_count', 0)} issued kits, and BDT {overview.get('total_revenue', 0):,.0f} total revenue captured for this event.",
        body_style,
    )

    elements = [header_table, Spacer(1, executive_spacing_after_header), executive_summary, Spacer(1, executive_spacing_after_summary), summary_cards, Spacer(1, 12), detail_row, Spacer(1, 12)]

    elements.append(Paragraph('GEOGRAPHY AND INSTITUTION MIX', section_kicker_style))
    elements.append(Paragraph('Where participants are coming from and which institutions are most represented', ParagraphStyle('EventPDFSectionTitle', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=15, leading=18, textColor=colors.HexColor('#0f172a'))))
    elements.append(Paragraph('Rankings are based on participant registration records for the selected event.', muted_style))
    elements.append(Spacer(1, 8))

    country_cards = []
    for row in countries[:4]:
        country_cards.append(stat_card(
            row.get('label', '-'),
            row.get('count', 0),
            'Participant registrations from this country',
            colors.HexColor('#bae6fd'),
            colors.HexColor('#f0f9ff'),
            colors.HexColor('#0f8aa8'),
        ))
    if country_cards:
        while len(country_cards) < 4:
            country_cards.append(Spacer(2.45 * inch, 0.1 * inch))
        country_summary = Table([country_cards], colWidths=[2.48 * inch, 2.48 * inch, 2.48 * inch, 2.48 * inch])
        country_summary.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.extend([country_summary, Spacer(1, 12)])

    max_institution = max([row.get('count', 0) for row in institutions], default=1) or 1
    institution_rows = [[Paragraph('Institution', table_head_style), Paragraph('Relative share', table_head_style), Paragraph('Count', table_head_style)]]
    for row in institutions[:10]:
        percent = round((row.get('count', 0) / max_institution) * 100) if max_institution else 0
        institution_rows.append([
            Paragraph(esc(row.get('label', '-')), table_cell_style),
            ranked_bar(percent, '#2563eb'),
            Paragraph(esc(row.get('count', 0)), ParagraphStyle('InstitutionCount', parent=table_cell_style, alignment=TA_CENTER, fontName='Helvetica-Bold')),
        ])
    if len(institution_rows) == 1:
        institution_rows.append([Paragraph('No institution data', table_cell_style), '', Paragraph('-', table_cell_style)])
    institution_table = Table(institution_rows, colWidths=[5.55 * inch, 3.9 * inch, 0.8 * inch], repeatRows=1)
    institution_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102033')),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#dbe4f0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5edf6')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fbff')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.extend([institution_table, Spacer(1, 16), PageBreak()])

    elements.append(Paragraph('DETAILED METRIC APPENDIX', section_kicker_style))
    elements.append(Paragraph('Event-wide operational counts', ParagraphStyle('EventPDFSectionTitleTwo', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=15, leading=18, textColor=colors.HexColor('#0f172a'))))
    elements.append(Paragraph('This appendix keeps the raw operational counts together for board review, internal reporting, and archive exports.', subtitle_style))
    elements.append(Paragraph('Attendance is currently represented by issued registration kits because that is the strongest attendance-like signal available in the live dataset. Country and institution rankings are based on participant registration data only.', muted_style))
    elements.append(Spacer(1, 10))

    detail_metrics = [
        ('Registrations started', overview.get('registrations_started', 0)),
        ('Approved participants', overview.get('approved', 0)),
        ('Pending participants', overview.get('pending', 0)),
        ('Denied participants', overview.get('denied', 0)),
        ('Members', overview.get('member_count', 0)),
        ('Regular', overview.get('regular_count', 0)),
        ('Company person', overview.get('company_person_count', 0)),
        ('Complementary', overview.get('complementary_count', 0)),
        ('Bangladesh participants', overview.get('bangladesh_count', 0)),
        ('Abroad participants', overview.get('abroad_count', 0)),
        ('Paid / completed participants', overview.get('participant_paid_count', 0)),
        ('Open / unpaid participants', overview.get('participant_unpaid_count', 0)),
        ('Failed / cancelled participants', overview.get('participant_failed_count', 0)),
        ('Attendance proxy (issued kit)', overview.get('attended_count', 0)),
        ('Attendance rate vs approved', f"{overview.get('attendance_rate', 0)}%"),
        ('Participant revenue', f"BDT {overview.get('participant_revenue', 0):,.2f}"),
        ('Corporate revenue', f"BDT {overview.get('corporate_revenue', 0):,.2f}"),
        ('Total revenue', f"BDT {overview.get('total_revenue', 0):,.2f}"),
        ('Corporate registrations', overview.get('corporate_registrations', 0)),
        ('Corporate attendees', overview.get('corporate_total_attendees', 0)),
        ('Corporate approved', overview.get('corporate_approved', 0)),
        ('Corporate pending', overview.get('corporate_pending', 0)),
        ('Corporate denied', overview.get('corporate_denied', 0)),
        ('Abstracts submitted', overview.get('abstracts_submitted', 0)),
        ('Approved for presentation', overview.get('abstracts_presentation', 0)),
        ('Approved for poster', overview.get('abstracts_poster', 0)),
        ('Abstracts pending', overview.get('abstracts_pending', 0)),
        ('Abstracts with files', overview.get('abstracts_with_files', 0)),
    ]

    metric_value_cell_style = ParagraphStyle('MetricValueCell', parent=table_cell_style, fontName='Helvetica-Bold')

    def build_metric_table(metric_rows):
        metrics_table_data = [[Paragraph('Metric', table_head_style), Paragraph('Value', table_head_style)]]
        for label, value in metric_rows:
            metrics_table_data.append([Paragraph(esc(label), table_cell_style), Paragraph(esc(value), metric_value_cell_style)])
        metrics_table = Table(metrics_table_data, colWidths=[2.9 * inch, 1.15 * inch], repeatRows=1)
        metrics_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102033')),
            ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#dbe4f0')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5edf6')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fbff')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        return metrics_table

    midpoint = (len(detail_metrics) + 1) // 2
    metrics_left = build_metric_table(detail_metrics[:midpoint])
    metrics_right = build_metric_table(detail_metrics[midpoint:])

    appendix_table = Table([[metrics_left, metrics_right]], colWidths=[4.2 * inch, 4.2 * inch])
    appendix_table.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(appendix_table)

    feedback_questions = feedback_report_data.get('questions', []) if event.event_status == 'closed' else []
    feedback_rows = feedback_report_data.get('rows', []) if event.event_status == 'closed' else []
    if event.event_status == 'closed' and (feedback_questions or feedback_rows):
        feedback_totals = feedback_report_data.get('totals', {})
        elements.extend([
            PageBreak(),
            Paragraph('FEEDBACK REPORT', section_kicker_style),
            Paragraph('Participant feedback insights and response appendix', title_style),
            Paragraph('This section is appended to the event report and mirrors the full feedback-report content for the same event.', subtitle_style),
            Spacer(1, 14),
        ])

        feedback_summary_cards = Table([[
            stat_card('Participants', feedback_totals.get('participants', 0), 'Submitted participants in this feedback report', colors.HexColor('#bfdbfe'), colors.HexColor('#eff6ff'), colors.HexColor('#1d4ed8')),
            stat_card('Submitted', feedback_totals.get('submitted', 0), 'Participants included in the feedback dataset', colors.HexColor('#bbf7d0'), colors.HexColor('#f0fdf4'), colors.HexColor('#15803d')),
            stat_card('Issued kits', feedback_totals.get('issued', 0), 'Submitted participants whose kits are already issued', colors.HexColor('#cbd5e1'), colors.HexColor('#f8fafc'), colors.HexColor('#0f172a')),
        ]], colWidths=[2.8 * inch, 2.8 * inch, 2.8 * inch])
        feedback_summary_cards.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.extend([feedback_summary_cards, Spacer(1, 18)])

        for index, insight in enumerate(feedback_report_data.get('insights', []), start=1):
            elements.append(Paragraph(f"QUESTION {index}", section_kicker_style))
            elements.append(Paragraph(insight['question'].question_text or f'Question {index}', feedback_question_title_style))
            elements.append(Paragraph(
                f"Type: <b>{insight['question'].get_question_type_display()}</b> &nbsp;&nbsp; | &nbsp;&nbsp; Answered by <b>{insight.get('answered_participants', 0)}/{insight.get('submitted_participants', 0)}</b> submitted participants.",
                body_style,
            ))
            elements.append(Spacer(1, 10))

            if insight.get('kind') == 'radio':
                radio_rows = [[
                    Paragraph('Option', table_head_style),
                    Paragraph('Count', table_head_style),
                    Paragraph('Share', table_head_style),
                    Paragraph('Distribution', table_head_style),
                ]]
                for bar in insight.get('bars', []):
                    radio_rows.append([
                        Paragraph(bar['label'], body_style),
                        Paragraph(str(bar['count']), table_cell_style),
                        Paragraph(f"{bar['percent']}%", table_cell_style),
                        ranked_bar(bar['percent'], '#2563eb'),
                    ])
                radio_table = Table(radio_rows, colWidths=[2.8 * inch, 0.8 * inch, 0.8 * inch, 3.3 * inch], repeatRows=1)
                radio_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102033')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#dbe4f0')),
                    ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5edf6')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fbff')]),
                    ('LEFTPADDING', (0, 0), (-1, -1), 8),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ]))
                elements.extend([radio_table, Spacer(1, 16)])

            elif insight.get('kind') == 'matrix':
                matrix_columns = insight.get('matrix_columns', [])
                matrix_data = [[Paragraph('Row', table_head_style)]]
                matrix_data[0].extend([Paragraph(str(column), table_head_style) for column in matrix_columns])
                matrix_data[0].append(Paragraph('Total', table_head_style))
                for row in insight.get('matrix_rows', []):
                    row_cells = [Paragraph(row['label'], body_style)]
                    for cell in row.get('cells', []):
                        cell_style = ParagraphStyle(
                            'EventPDFFeedbackMatrixCell',
                            parent=table_cell_style,
                            textColor=colors.white if cell.get('use_light_text') else colors.HexColor('#1d4ed8'),
                        )
                        row_cells.append(Paragraph(str(cell['count']), cell_style))
                    row_cells.append(Paragraph(str(row.get('total', 0)), table_cell_style))
                    matrix_data.append(row_cells)
                matrix_table = Table(matrix_data, repeatRows=1)
                matrix_style = [
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102033')),
                    ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#dbe4f0')),
                    ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5edf6')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 7),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('BACKGROUND', (0, 1), (0, -1), colors.white),
                    ('BACKGROUND', (-1, 1), (-1, -1), colors.HexColor('#f8fafc')),
                ]
                for row_index, row in enumerate(insight.get('matrix_rows', []), start=1):
                    for col_index, cell in enumerate(row.get('cells', []), start=1):
                        if cell.get('intensity'):
                            matrix_style.append(('BACKGROUND', (col_index, row_index), (col_index, row_index), colors.Color(37/255, 99/255, 235/255, alpha=min(cell['intensity'] / 100, 0.95))))
                        else:
                            matrix_style.append(('BACKGROUND', (col_index, row_index), (col_index, row_index), colors.HexColor('#f8fafc')))
                matrix_table.setStyle(TableStyle(matrix_style))
                elements.extend([matrix_table, Spacer(1, 16)])

            else:
                all_text_answers = list(insight.get('text_answers', []))
                longest_text_answers = sorted(all_text_answers, key=lambda answer: (len(answer or ''), answer or ''), reverse=True)[:10]
                elements.append(Paragraph(f"{insight.get('response_count', 0)} text response(s) captured for this question. Showing the 10 longest responses in the PDF summary.", body_style))
                elements.append(Spacer(1, 8))
                text_rows = [[Paragraph('No.', table_head_style), Paragraph('Response', table_head_style)]]
                for answer_index, answer in enumerate(longest_text_answers, start=1):
                    text_rows.append([
                        Paragraph(str(answer_index), table_cell_style),
                        Paragraph(answer.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>'), feedback_answer_style),
                    ])
                if len(text_rows) == 1:
                    text_rows.append([Paragraph('-', table_cell_style), Paragraph('No saved text responses yet.', body_style)])
                text_table = Table(text_rows, colWidths=[0.45 * inch, 9.1 * inch], repeatRows=1)
                text_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102033')),
                    ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#dbe4f0')),
                    ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5edf6')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fbff')]),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 7),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ]))
                elements.extend([text_table, Spacer(1, 16)])

        elements.extend([
            PageBreak(),
            Paragraph('PARTICIPANT APPENDIX', section_kicker_style),
            Paragraph('Submitted participant response index', title_style),
            Paragraph('This appendix lists submitted participants and their eligibility-related status at the time of export.', subtitle_style),
            Spacer(1, 12),
        ])

        appendix_rows = [[
            Paragraph('Participant', feedback_appendix_head_style),
            Paragraph('Email', feedback_appendix_head_style),
            Paragraph('Invoice', feedback_appendix_head_style),
            Paragraph('Approved', feedback_appendix_head_style),
            Paragraph('Payment', feedback_appendix_head_style),
            Paragraph('Kit', feedback_appendix_head_style),
            Paragraph('Answered', feedback_appendix_head_style),
        ]]
        for row in feedback_rows:
            appendix_rows.append([
                Paragraph((row['participant'].name or '-').replace('&', '&amp;'), feedback_appendix_cell_style),
                Paragraph((row['participant'].email or '-').replace('&', '&amp;'), feedback_appendix_cell_style),
                Paragraph((row.get('invoice_number') or '-').replace('&', '&amp;'), feedback_appendix_cell_style),
                Paragraph('Yes' if row['participant'].approved else 'No', feedback_appendix_cell_style),
                Paragraph(getattr(row.get('payment_status'), 'status', 'Unpaid').title() if row.get('payment_status') else 'Unpaid', feedback_appendix_cell_style),
                Paragraph('Issued' if row.get('kit_issued') else 'Not issued', feedback_appendix_cell_style),
                Paragraph(f"{row.get('answered_questions', 0)}/{len(feedback_questions)}", feedback_appendix_cell_style),
            ])
        appendix_feedback_table = Table(appendix_rows, colWidths=[1.7 * inch, 2.2 * inch, 1.4 * inch, 0.65 * inch, 0.9 * inch, 0.8 * inch, 0.8 * inch], repeatRows=1)
        appendix_feedback_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102033')),
            ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#dbe4f0')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5edf6')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fbff')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(appendix_feedback_table)

    doc.build(elements, canvasmaker=EventReportCanvas)
    buffer.seek(0)
    return buffer
