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

from io import BytesIO
from reportlab.lib.pagesizes import inch, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch

def generate_schedule_pdf(event, schedules):
    # New schedule renderer: build day -> rows (slot or session) similar to schedule.html
    custom_paper_size = (11 * inch, 17 * inch)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(custom_paper_size),
                            rightMargin=0.5 * inch, leftMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    body = styles['BodyText']
    title_style = styles['Title']
    small_bold = ParagraphStyle('SmallBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=11, textColor=colors.HexColor('#102033'))
    accent = colors.HexColor('#be185d')

    elements = []

    # Header block
    header = Paragraph(f"{event.name} {event.year} — Program Schedule", title_style)
    elements.append(header)
    elements.append(Spacer(1, 12))

    # Build schedule data from provided schedules (legacy) for compatibility, but also try to derive slots & sessions
    # We'll attempt to collect time slots and sessions similar to the HTML view.
    from .models import TimeSlot, ProgramSession
    from collections import defaultdict

    # Collect time slots for the event
    time_slots = TimeSlot.objects.filter(event=event).select_related('program_day', 'hall_room').order_by('program_day__date', 'start_time', 'hall_room__name')
    program_sessions = ProgramSession.objects.filter(event=event).select_related('program_day', 'hall_room', 'time_slot').prefetch_related('faculty_roles__person', 'items__faculty_roles__person')

    # Group slots by day
    slots_by_day = defaultdict(list)
    for slot in time_slots:
        slots_by_day[slot.program_day_id].append(slot)

    # Group sessions by time-window so parallels are detected
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

    # Organize by day and render blocks
    from reportlab.lib.enums import TA_LEFT
    para_style = ParagraphStyle('para', parent=styles['Normal'], alignment=TA_LEFT, fontSize=9, leading=11)

    # Helper to render a session block as a two-column table (time/room | content)
    def session_block(session):
        time_text = f"{session.start_time.strftime('%I:%M %p')} — {session.end_time.strftime('%I:%M %p')}"
        left = Paragraph(f"<b>{time_text}</b><br/><font size=8>{session.hall_room.name if session.hall_room else ''}</font>", para_style)

        # Build right column HTML-like content
        # Title and parallel badge
        time_window = (session.program_day_id, session.start_time, session.end_time)
        parallel_count = len(sessions_by_time_window.get(time_window, []))
        badge = f" <font color='#b91c6b'><b>PARALLEL ({parallel_count})</b></font>" if parallel_count > 1 else ""
        title_html = f"<b>{session.title}</b>{badge}"
        parts = [Paragraph(title_html, small_bold)]
        if getattr(session, 'description', None):
            parts.append(Paragraph(session.description, para_style))

        # Roles
        # grouped by role label
        try:
            grouped = {}
            for role in session.faculty_roles.all():
                label = role.get_role_display()
                grouped.setdefault(label, []).append(role.person.name)
            for label, names in grouped.items():
                parts.append(Paragraph(f"<font color='{accent.hexval()}'><b>{label}</b></font>", para_style))
                parts.append(Paragraph(', '.join(names), para_style))
        except Exception:
            pass

        # Items (topics & speakers)
        try:
            for item in session.items.all():
                parts.append(Paragraph(f"<b>{item.display_title}</b>", para_style))
                if getattr(item, 'start_time', None) and getattr(item, 'end_time', None):
                    parts.append(Paragraph(f"<font size=8>{item.start_time.strftime('%I:%M %p')} - {item.end_time.strftime('%I:%M %p')}</font>", para_style))
                # speaker/presenter label
                sp = ''
                try:
                    speakers = [r.person.name for r in item.faculty_roles.all() if r.role == getattr(r, 'ROLE_SPEAKER', 'speaker')]
                    presenters = [r.person.name for r in item.faculty_roles.all() if r.role == getattr(r, 'ROLE_PRESENTER', 'presenter')]
                    sp = ', '.join(speakers) if speakers else ', '.join(presenters)
                except Exception:
                    sp = ''
                if sp:
                    parts.append(Paragraph(f"<font color='{accent.hexval()}' size=9>{sp}</font>", para_style))
        except Exception:
            pass

        right = parts
        tbl = Table([[left, right]], colWidths=[1.6 * inch, 9.4 * inch])
        tbl.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('BACKGROUND', (0, 0), (-1, -1), colors.white),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#fbcfe8')),
        ]))
        return tbl

    def slot_block(slot):
        # Break/meal/ceremony style
        label = slot.label or slot.get_slot_type_display()
        time_text = f"{slot.start_time.strftime('%I:%M %p')} — {slot.end_time.strftime('%I:%M %p')}"
        content = Paragraph(f"<b>{label}</b><br/><font size=9>{slot.hall_room.name}</font>", para_style)
        tbl = Table([[Paragraph(time_text, para_style), content]], colWidths=[1.6 * inch, 9.4 * inch])
        # color accent based on slot type
        color_map = {
            'tea_break': colors.HexColor('#fef3c7'),
            'lunch': colors.HexColor('#d1fae5'),
            'dinner': colors.HexColor('#ede9fe'),
            'ceremony': colors.HexColor('#dbeafe'),
        }
        bg = color_map.get(slot.slot_type, colors.whitesmoke)
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), bg),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        return tbl

    # Determine program days from time_slots (preserve order)
    days = []
    from registration.models import ProgramDay
    pd_qs = ProgramDay.objects.filter(event=event).order_by('date', 'name')
    for pd in pd_qs:
        days.append(pd)

    for day in days:
        # Day header
        day_header = Table([[Paragraph(f"<b>{day.name} - {day.date.strftime('%A, %B %d, %Y')}</b>", small_bold)]], colWidths=[11 * inch])
        day_header.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), accent),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(day_header)
        elements.append(Spacer(1, 6))

        # rows: iterate through slots for that day
        for slot in slots_by_day.get(day.id, []):
            if slot.slot_type == TimeSlot.SLOT_SESSION:
                # render each session assigned to this slot
                slot_sessions = sessions_by_slot.get(slot.id, [])
                for s in slot_sessions:
                    elements.append(session_block(s))
                    elements.append(Spacer(1, 6))
            else:
                elements.append(slot_block(slot))
                elements.append(Spacer(1, 6))

        # unassigned sessions for day
        for s in unassigned_sessions_by_day.get(day.id, []):
            elements.append(session_block(s))
            elements.append(Spacer(1, 6))

        elements.append(Spacer(1, 12))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# Schedule Generation in pdf generator end ----------------------------------------------------------------

# Invoice Generation in pdf generator start ----------------------------------------------------------------
import os
from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, inch
from reportlab.platypus import Table, TableStyle
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_RIGHT

def generate_invoice(participant, event, payment_status):
    from .qr_utils import ensure_registration_qr

    invoice_amount = payment_status.amount or 0
    qr_path = ensure_registration_qr(payment_status)
    # Generate the filename based on payment status ID
    file_name = f"invoice_{payment_status.id}.pdf"
    
    # Create the directory if it doesn't exist
    invoices_dir = os.path.join(settings.MEDIA_ROOT, 'invoices')
    os.makedirs(invoices_dir, exist_ok=True)
    
    # File path for the invoice PDF
    file_path = os.path.join(invoices_dir, file_name)

    # Create a canvas object for generating the PDF
    c = canvas.Canvas(file_path, pagesize=letter)
    margin = 50
    space_between_sections = 30  # Space between sections for visual clarity
    section_height = 20  # Height for each section's content before adding space
    content_top = letter[1] - 100  # Start content slightly below the top to make room for the header

    # First Section: "Invoice" Header (Centered)
    c.setFont("Helvetica-Bold", 18)
    c.drawString((letter[0] - c.stringWidth("Invoice", "Helvetica-Bold", 18)) / 2, content_top, "Invoice")

    # Add a bottom border for the header section
    c.setStrokeColor(colors.black)
    c.setLineWidth(1)
    c.line(margin, content_top - 20, letter[0] - margin, content_top - 20)

    # Move down after header
    content_top -= 20  # Adjust spacing after the header

    # Second Section: Event Logo (if available) and Event Name/Year (now only the logo)
    logo_path = os.path.join(settings.MEDIA_ROOT, event.event_logo.name) if event.event_logo else None
    if logo_path and os.path.exists(logo_path):
        logo_width = 1.5 * inch  # Adjust width of the logo
        logo_height = 1.5 * inch  # Adjust height of the logo
        c.drawImage(logo_path, margin, content_top, width=logo_width, height=logo_height, preserveAspectRatio=True, mask='auto')

    # Event Date under logo
    c.setFont("Helvetica", 10)
    c.drawString(margin, content_top - 20, f"Event Name: {event.name} {event.year}")

    # Add a bottom border for the logo section
    c.line(margin, content_top - 30, letter[0] - margin, content_top - 30)

    # Move down after the logo section
    content_top -= 30  # Move down for the next section

    # Third Section: Participant and Event Details
    details = [
        f"Participant Name: {participant.name}",
        f"Merchant Invoice Number: {payment_status.merchant_invoice_number}",
        f"Event Date: {event.start_date.strftime('%B %d, %Y')}",
        f"Location: {event.location}"
    ]
    
    detail_start_y = content_top - 30
    for i, detail in enumerate(details):
        c.drawString(margin, detail_start_y - (i * section_height), detail)

    details_bottom_y = detail_start_y - ((len(details) - 1) * section_height)
    # Add a bottom border for the details section
    c.line(margin, details_bottom_y - 20, letter[0] - margin, details_bottom_y - 20)

    # Add space before the table
    content_top -= 1  # Move content down before table

    # Fourth Section: Invoice Table for Fees
    data = [
        ["Description", "Quantity", "Unit Price", "Total"],
        [f"Registration fees for {event.name} {event.year}", "1", f"BDT {invoice_amount}", f"BDT {invoice_amount}"]
    ]
    
    table = Table(data, colWidths=[250, 80, 80, 100])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    table.wrapOn(c, margin, content_top - 250)
    table.drawOn(c, margin, content_top - 200)

    # Add a bottom border for the table section
    c.line(margin, content_top - 230, letter[0] - margin, content_top - 230)

    # Total Amount Section
    c.setFont("Helvetica-Bold", 12)
    c.drawString(letter[0] - margin - 150, content_top - 250, f"Total: BDT {invoice_amount}")

    # Bottom-left QR code block above the footer
    if qr_path and os.path.exists(qr_path):
        qr_size = 1.25 * inch
        qr_x = margin
        qr_y = margin + 70
        c.drawImage(qr_path, qr_x, qr_y, width=qr_size, height=qr_size, preserveAspectRatio=True, mask='auto')
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(qr_x + (qr_size / 2), qr_y - 10, "SCAN AT REGISTRATION DESK")
        c.setFont("Helvetica", 7)
        c.drawCentredString(qr_x + (qr_size / 2), qr_y - 20, f"{participant.name[:32]}")

    # Footer Section with Thank You and Signature Message
    footer_y = margin + 45
    c.setFont("Helvetica", 10)
    c.drawString(margin, footer_y, "Thank you for registering!")
    c.drawString(margin, footer_y - 20, "This is a computer-generated invoice and does not need any signature.")

    # Add a bottom border for the footer section
    c.line(margin, footer_y - 30, letter[0] - margin, footer_y - 30)

    # Save the PDF file
    c.save()
    
    return file_path

# Invoice Generation End ----------------------------------------------------------------


def _format_bdt(amount):
    amount = amount or 0
    return f"BDT {float(amount):,.2f}"


def _get_site_invoice_logo_path():
    try:
        from website.models import SiteSettings

        site_settings = SiteSettings.objects.first()
        if not site_settings:
            return None
        logo = site_settings.membership_invoice_logo or site_settings.logo
        if logo and os.path.exists(logo.path):
            return logo.path
    except Exception:
        return None
    return None


def generate_corporate_invoice(corporate_payment):
    from .qr_utils import ensure_registration_qr
    from .models import PaymentStatus

    event = corporate_payment.event
    account = corporate_payment.corporate_account
    is_paid = corporate_payment.status in ['completed', 'paid']
    payment_label = 'PAID' if is_paid else 'UNPAID'
    status_color = colors.HexColor('#15803d') if is_paid else colors.HexColor('#b45309')
    status_background = colors.HexColor('#dcfce7') if is_paid else colors.HexColor('#fef3c7')
    file_name = f"corporate_invoice_{corporate_payment.id}.pdf"
    invoices_dir = os.path.join(settings.MEDIA_ROOT, 'media', 'corporate_invoices')
    os.makedirs(invoices_dir, exist_ok=True)
    file_path = os.path.join(invoices_dir, file_name)

    doc = SimpleDocTemplate(
        file_path,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=42,
        bottomMargin=42,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='InvoiceTitle',
        parent=styles['Title'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        spaceAfter=12,
        textColor=colors.HexColor('#102033'),
    ))
    styles.add(ParagraphStyle(
        name='BrandName',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=17,
        textColor=colors.HexColor('#1565c0'),
    ))
    styles.add(ParagraphStyle(
        name='SmallMuted',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#5f6b7a'),
    ))
    styles.add(ParagraphStyle(
        name='RightTotal',
        parent=styles['Normal'],
        alignment=TA_RIGHT,
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#102033'),
    ))
    status_style = ParagraphStyle(
        name='CorporateInvoiceStatus',
        parent=styles['Normal'],
        alignment=1,
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=13,
        textColor=status_color,
    )

    logo_path = _get_site_invoice_logo_path()
    brand_cell = Paragraph("<b>BSBCS</b><br/><font size='9'>Bangladesh Society For Breast Cancer Study</font>", styles['BrandName'])
    if logo_path:
        logo_image = Image(logo_path, width=0.75 * inch, height=0.75 * inch)
        brand_cell = Table([[logo_image, brand_cell]], colWidths=[58, 210])
        brand_cell.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

    status_badge = Table(
        [[Paragraph(payment_label, status_style)]],
        colWidths=[92],
        rowHeights=[28],
    )
    status_badge.setStyle(TableStyle([
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

    header_table = Table([
        [
            brand_cell,
            Paragraph(
                f"<b>Corporate Invoice</b><br/>"
                f"<font size='9'>Invoice: {corporate_payment.merchant_invoice_number}</font><br/>"
                f"<font size='9'>System status: {corporate_payment.get_status_display()}</font>",
                styles['Normal'],
            ),
            status_badge,
        ]
    ], colWidths=[270, 150, 100])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 0), (-1, -1), 1, colors.HexColor('#dce3ec')),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
    ]))

    elements = [
        header_table,
        Spacer(1, 18),
        Paragraph("Corporate Event Registration Invoice", styles['InvoiceTitle']),
        Spacer(1, 4),
    ]

    info_data = [
        [
            Paragraph(
                f"<b>Bill To</b><br/>{account.company_name}<br/>{account.contact_name}<br/>{account.email}<br/>{account.phone}",
                styles['Normal']
            ),
            Paragraph(
                f"<b>Event</b><br/>{event.name} {event.year}<br/>"
                f"{event.start_date.strftime('%B %d, %Y') if event.start_date else ''}<br/>"
                f"{event.location or ''}",
                styles['Normal']
            ),
        ]
    ]
    info_table = Table(info_data, colWidths=[250, 250])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#dce3ec')),
        ('INNERGRID', (0, 0), (-1, -1), 0.75, colors.HexColor('#dce3ec')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.extend([info_table, Spacer(1, 18)])

    attendee_rows = [[
        Paragraph("<b>Attendee</b>", styles['SmallMuted']),
        Paragraph("<b>Contact</b>", styles['SmallMuted']),
        Paragraph("<b>Fee category</b>", styles['SmallMuted']),
        Paragraph("<b>Amount</b>", styles['SmallMuted']),
    ]]
    attendees = corporate_payment.attendees.select_related('participant', 'matched_user').all()
    for attendee in attendees:
        amount = attendee.participant.get_payable_amount() if attendee.participant else 0
        attendee_rows.append([
            Paragraph(attendee.name or "-", styles['Normal']),
            Paragraph(f"{attendee.email}<br/>{attendee.phone}", styles['SmallMuted']),
            Paragraph(attendee.applied_fee_label, styles['SmallMuted']),
            Paragraph(_format_bdt(amount), styles['SmallMuted']),
        ])

    if len(attendee_rows) == 1:
        attendee_rows.append([
            Paragraph("Corporate event registration", styles['Normal']),
            Paragraph("-", styles['SmallMuted']),
            Paragraph("Summary invoice", styles['SmallMuted']),
            Paragraph(_format_bdt(corporate_payment.amount), styles['SmallMuted']),
        ])

    attendee_table = Table(attendee_rows, colWidths=[160, 150, 130, 80], repeatRows=1)
    attendee_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#102033')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#dce3ec')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e8edf4')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))

    qr_path = None
    for attendee in attendees:
        if not attendee.participant:
            continue
        participant_payment = PaymentStatus.objects.filter(
            participant=attendee.participant,
            event=event,
        ).first()
        if not participant_payment:
            continue
        temp_path = ensure_registration_qr(participant_payment)
        if temp_path and os.path.exists(temp_path):
            qr_path = temp_path
            break

    elements.extend([
        attendee_table,
        Spacer(1, 16),
        Paragraph(f"Total payable: {_format_bdt(corporate_payment.amount)}", styles['RightTotal']),
        Spacer(1, 24),
    ])

    if qr_path:
        qr_image = Image(qr_path, width=1.5 * inch, height=1.5 * inch)
        qr_block = Table(
            [[
                Paragraph("This is a computer-generated invoice and does not need any signature.", styles['SmallMuted']),
                qr_image,
            ]],
            colWidths=[360, 108],
            hAlign='LEFT'
        )
        qr_block.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.extend([
            Spacer(1, 24),
            qr_block,
            Spacer(1, 12),
        ])
    else:
        elements.extend([
            Paragraph("This is a computer-generated invoice and does not need any signature.", styles['SmallMuted']),
        ])

    doc.build(elements)
    corporate_payment.invoice.name = f"media/corporate_invoices/{file_name}"
    corporate_payment.save(update_fields=['invoice', 'updated_at'])
    return file_path
