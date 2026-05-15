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
    custom_paper_size = (11 * inch, 17 * inch)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(custom_paper_size),
                            rightMargin=0.5 * inch, leftMargin=0.5 * inch,
                            topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    elements = []

    # Define the Header
    header = Paragraph(f"Program Schedule of {event.name} {event.year}", styles['Title'])
    elements.append(header)
    elements.append(Spacer(1, 24))

    data = [['Day', 'Time', 'Title', 'Presenter', 'Hall Room', 'Chairperson', 'Panelist', 'Moderator']]

    for schedule in schedules:
        for slot in schedule.time_slots.all():
            day = Paragraph(str(slot.program_day), styles['BodyText'])
            time = Paragraph(f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}", styles['BodyText'])
            title = Paragraph(schedule.title, styles['BodyText'])
            presenter = Paragraph(schedule.presenter, styles['BodyText'])
            hall_room = Paragraph(slot.hall_room.name, styles['BodyText'])

            # Convert chairperson, panelist, and moderator to strings
            chairperson = Paragraph(str(schedule.chairperson), styles['BodyText']) if schedule.chairperson else ""
            panelist = Paragraph(', '.join([str(p) for p in schedule.panelist.all()]), styles['BodyText'])
            moderator = Paragraph(str(schedule.moderator), styles['BodyText']) if schedule.moderator else ""

            row = [day, time, title, presenter, hall_room, chairperson, panelist, moderator]
            data.append(row)

    # Adjust column widths to fit within the landscape A4-sized page.
    table = Table(data, colWidths=[1.5 * inch, 2 * inch, 3 * inch, 2.5 * inch, 1.5 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.pink),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))

    elements.append(table)
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

def generate_invoice(participant, event, payment_status):
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
    
    for i, detail in enumerate(details):
        c.drawString(margin, content_top - 30 - (i * section_height), detail)
    
    # Add a bottom border for the section
    c.line(margin, content_top - 60 - (i * section_height), letter[0] - margin, content_top - 60 - (i * section_height))

    # Add space before the table
    content_top -= 1  # Move content down before table

    # Fourth Section: Invoice Table for Fees
    data = [
        ["Description", "Quantity", "Unit Price", "Total"],
        [f"Registration fees for {event.name} {event.year}", "1", f"BDT {event.amount}", f"BDT {event.amount}"]
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
    c.drawString(letter[0] - margin - 150, content_top - 250, f"Total: BDT {event.amount}")

    # Footer Section with Thank You and Signature Message
    c.setFont("Helvetica", 10)
    c.drawString(margin, content_top - 280, "Thank you for registering!")
    c.drawString(margin, content_top - 300, "This is a computer-generated invoice and does not need any signature.")

    # Add a bottom border for the footer section
    c.line(margin, content_top - 350, letter[0] - margin, content_top - 350)

    # Save the PDF file
    c.save()
    
    return file_path

# Invoice Generation End ----------------------------------------------------------------