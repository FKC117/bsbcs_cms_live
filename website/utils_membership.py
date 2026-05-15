import os
from io import BytesIO
from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from dateutil.relativedelta import relativedelta

def generate_membership_invoice(payment):
    """
    Generates a PDF invoice for a membership payment.
    Returns the file path.
    """
    file_name = f"membership_invoice_{payment.id}.pdf"
    invoices_dir = os.path.join(settings.MEDIA_ROOT, 'membership_invoices')
    os.makedirs(invoices_dir, exist_ok=True)
    file_path = os.path.join(invoices_dir, file_name)

    # Create canvas
    c = canvas.Canvas(file_path, pagesize=letter)
    width, height = letter
    margin = 50
    content_top = height - 50

    # Header section
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width / 2, content_top, "MEMBERSHIP INVOICE")
    
    # Border below header
    content_top -= 10
    c.setStrokeColor(colors.black)
    c.setLineWidth(1)
    c.line(margin, content_top, width - margin, content_top)
    
    # Site Logo / Branding
    # We try to get invoice logo from site settings
    from .models import SiteSettings
    site_settings = SiteSettings.objects.first()
    
    logo_path = None
    if site_settings and site_settings.membership_invoice_logo:
        logo_path = site_settings.membership_invoice_logo.path
    elif site_settings and site_settings.logo:
        logo_path = site_settings.logo.path

    content_top -= 60
    if logo_path and os.path.exists(logo_path):
        c.drawImage(logo_path, margin, content_top, width=1.5*inch, height=0.6*inch, preserveAspectRatio=True, mask='auto')
    
    # Organization Name
    org_name = site_settings.site_name if site_settings else "BSBCS"
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, content_top - 20, org_name)
    c.setFont("Helvetica", 10)
    c.drawString(margin, content_top - 35, "Bangladesh Society for Breast Cancer Study")

    # Invoice Info (Right aligned)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(width - margin, content_top, f"Invoice #: {payment.merchant_invoice_number}")
    c.setFont("Helvetica", 10)
    c.drawRightString(width - margin, content_top - 15, f"Date: {payment.created_at.strftime('%B %d, %Y')}")
    c.drawRightString(width - margin, content_top - 30, f"Status: {payment.status.upper()}")

    # Bill To
    content_top -= 80
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, content_top, "BILL TO:")
    c.setFont("Helvetica", 11)
    c.drawString(margin, content_top - 20, payment.user_profile.name)
    c.drawString(margin, content_top - 35, payment.user_profile.email)
    c.drawString(margin, content_top - 50, payment.user_profile.phone or "")

    # Table
    content_top -= 90
    data = [
        ["Description", "Type", "Duration", "Amount"],
        [
            f"Membership Subscription",
            payment.membership_type.name if payment.membership_type else "General",
            "Lifetime" if (payment.membership_type and payment.membership_type.is_lifetime) or payment.duration_years >= 100 else f"{payment.duration_years} Year(s)",
            f"BDT {payment.amount}"
        ]
    ]

    table = Table(data, colWidths=[250, 100, 80, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1f2937")), # Gray-800
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    
    table_height = 40 # Roughly
    table.wrapOn(c, margin, content_top - table_height)
    table.drawOn(c, margin, content_top - table_height)

    # Totals
    content_top -= (table_height + 40)
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(width - margin, content_top, f"TOTAL: BDT {payment.amount}")

    # Footer
    c.setFont("Helvetica-Oblique", 8)
    footer_text = "This is a computer-generated invoice and does not require a physical signature."
    c.drawCentredString(width / 2, margin, footer_text)

    c.save()
    return file_path

def send_membership_invoice_email(payment):
    """
    Sends the membership invoice to the member via email.
    """
    if not payment.invoice:
        return False
        
    subject = f"Membership Invoice - {payment.merchant_invoice_number}"
    message = f"Dear {payment.user_profile.name},\n\nThank you for your membership subscription. Please find your invoice attached.\n\nBest regards,\nBSBCS Team"
    recipient_list = [payment.user_profile.email]
    
    email = EmailMessage(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        recipient_list
    )
    
    if os.path.exists(payment.invoice.path):
        email.attach_file(payment.invoice.path)
        try:
            email.send()
            return True
        except Exception as e:
            import logging
            logger = logging.getLogger('django')
            logger.error(f"Failed to send membership invoice email: {str(e)}")
            return False
    return False


def complete_membership_payment(payment_record):
    """
    Centralized logic to complete a membership payment.
    - Updates payment status
    - Activates/Extends member subscription
    - Generates PDF invoice
    - Sends invoice email
    """
    from .models import Member
    import logging
    logger = logging.getLogger('payment')

    # 1. Update Payment Status
    payment_record.status = 'completed'
    payment_record.save()

    # 2. Get/Activate Member
    member, created = Member.objects.get_or_create(user_profile=payment_record.user_profile)
    member.is_active_member = True
    
    # Calculate subscription dates
    now = timezone.now().date()
    if not member.subscription_start_date or not member.subscription_expiry_date or member.subscription_expiry_date < now:
        member.subscription_start_date = now
        current_expiry = now
    else:
        current_expiry = member.subscription_expiry_date

    # Extend from current expiry (or today) by the duration years
    member.subscription_expiry_date = current_expiry + relativedelta(years=payment_record.duration_years)
    member.membership_type = payment_record.membership_type
    member.save()

    # 3. Generate and Save Invoice
    try:
        invoice_path = generate_membership_invoice(payment_record)
        
        # Save path relative to MEDIA_ROOT
        relative_path = os.path.relpath(invoice_path, settings.MEDIA_ROOT)
        payment_record.invoice = relative_path
        payment_record.save()
        
        # 4. Send Email
        send_membership_invoice_email(payment_record)
        return True
    except Exception as e:
        logger.error(f"Error in automatic post-payment processing: {str(e)}")
        return False
