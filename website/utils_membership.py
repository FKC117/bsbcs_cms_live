import os
from io import BytesIO
from django.conf import settings
from registration.tasks import send_email_task
from registration.sms import queue_membership_payment_received_sms
from registration.models import EmailAuditLog
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from dateutil.relativedelta import relativedelta
from invoice_shared import build_footer_block, build_info_table, build_invoice_header, build_invoice_styles, build_invoice_title_block, build_line_items_table, build_total_block, format_bdt


def ensure_membership_payment_for_member(member):
    """
    Ensure an approved, inactive member has one open membership payment row.

    Approval makes the member eligible to pay. Completion still happens only
    when the payment status becomes completed.
    """
    from .models import MembershipPayment

    if not member or not member.user_profile_id:
        return None
    if member.approval_status != 'approved' or member.is_active_member:
        return None
    if not member.membership_type_id:
        return None

    open_payment = MembershipPayment.objects.filter(
        user_profile=member.user_profile,
    ).exclude(status='completed').order_by('-created_at').first()
    if open_payment:
        return open_payment

    invoice_number = f"MEM-{member.id}-{int(timezone.now().timestamp())}"
    return MembershipPayment.objects.create(
        user_profile=member.user_profile,
        membership_type=member.membership_type,
        duration_years=member.membership_type.duration_years or 1,
        amount=member.membership_type.amount,
        merchant_invoice_number=invoice_number,
        status='initiated',
    )


def generate_membership_invoice(payment):
    """
    Generates a PDF invoice for a membership payment.
    Returns the file path.
    """
    file_name = f"membership_invoice_{payment.id}.pdf"
    invoices_dir = os.path.join(settings.MEDIA_ROOT, 'membership_invoices')
    os.makedirs(invoices_dir, exist_ok=True)
    file_path = os.path.join(invoices_dir, file_name)

    from .models import SiteSettings

    site_settings = SiteSettings.objects.first()
    logo_path = None
    if site_settings and site_settings.membership_invoice_logo:
        logo_path = site_settings.membership_invoice_logo.path
    elif site_settings and site_settings.logo:
        logo_path = site_settings.logo.path

    abbreviation = (site_settings.abbreviation or '').strip() if site_settings else ''
    site_name = (site_settings.site_name or '').strip() if site_settings else ''
    tag_line = (site_settings.tag_line or '').strip() if site_settings else ''
    org_name = abbreviation or site_name or 'BSBCS'
    subtitle = site_name if site_name and abbreviation and site_name.lower() != abbreviation.lower() else (tag_line or site_name or 'Bangladesh Society for Breast Cancer Study')
    styles = build_invoice_styles()
    status_text = payment.get_status_display() if hasattr(payment, 'get_status_display') else str(payment.status).title()
    invoice_dt = timezone.localtime(timezone.now())
    invoice_date = invoice_dt.strftime('%B %d, %Y')
    invoice_time = invoice_dt.strftime('%I:%M %p')
    duration_label = (
        'Lifetime'
        if (payment.membership_type and payment.membership_type.is_lifetime) or payment.duration_years >= 100
        else f'{payment.duration_years} Year(s)'
    )

    doc = SimpleDocTemplate(
        file_path,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=42,
        bottomMargin=42,
    )

    rows = [[
        Paragraph('Membership subscription', styles['BodyCell']),
        Paragraph(payment.membership_type.name if payment.membership_type else 'General', styles['BodyCell']),
        Paragraph(duration_label, styles['SmallMuted']),
        Paragraph(format_bdt(payment.amount), styles['BodyCellRight']),
    ]]

    elements = [
        build_invoice_header(
            styles,
            logo_path,
            'Membership Invoice',
            payment.merchant_invoice_number,
            status_text,
            org_name=org_name,
            subtitle=subtitle,
            metadata_lines=[f'Invoice date: {invoice_date}', f'Generated at: {invoice_time}'],
        ),
        Spacer(1, 18),
        build_invoice_title_block(styles, 'Membership Subscription Invoice', 'Membership fee summary and subscription term details.'),
        Spacer(1, 10),
        build_info_table(
            styles,
            'Bill To',
            [payment.user_profile.name, payment.user_profile.email, payment.user_profile.phone or ''],
            'Membership',
            [
                payment.membership_type.name if payment.membership_type else 'General',
                duration_label,
                payment.created_at.strftime('%B %d, %Y'),
                f'Status: {status_text}',
            ],
        ),
        Spacer(1, 18),
        build_line_items_table(styles, ['Description', 'Type', 'Duration', 'Amount'], rows, [250, 100, 80, 80]),
        Spacer(1, 16),
        build_total_block(styles, 'Total payable', format_bdt(payment.amount)),
        Spacer(1, 24),
        build_footer_block(styles, 'This is a computer-generated invoice and does not require a physical signature.'),
    ]

    doc.build(elements)
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
    
    if os.path.exists(payment.invoice.path):
        try:
            send_email_task.delay(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[payment.user_profile.email],
                attachment_paths=[payment.invoice.path],
                audit_category=EmailAuditLog.CATEGORY_MEMBERSHIP,
                audit_metadata={
                    'membership_payment_id': payment.id,
                    'user_profile_id': payment.user_profile_id,
                    'merchant_invoice_number': payment.merchant_invoice_number,
                },
            )
            return True
        except Exception as e:
            import logging
            logger = logging.getLogger('django')
            logger.error(f"Failed to queue membership invoice email: {str(e)}")
            return False
    return False


def process_pending_event_intents(member):
    """
    Convert saved member-event intents into pending event participants.

    This keeps event approval with admins: the participant is created, but not
    marked approved.
    """
    import logging
    import time
    from django.db import IntegrityError
    from registration.models import Department, Participant, PaymentStatus
    from .models import PendingEventIntent

    logger = logging.getLogger('payment')
    pending_intents = PendingEventIntent.objects.filter(
        user_profile=member.user_profile,
        intent_type='member_registration',
        status='pending',
    ).select_related('event', 'user_profile')

    for intent in pending_intents:
        event = intent.event

        if event.registration != 'Open' or event.event_status != 'active':
            intent.status = 'failed'
            intent.note = 'Event registration was not open when membership became active.'
            intent.save(update_fields=['status', 'note', 'updated_at'])
            continue

        if not event.member_registration_enabled and event.registration_audience != 'members_only':
            intent.status = 'failed'
            intent.note = 'Event no longer allows member registration.'
            intent.save(update_fields=['status', 'note', 'updated_at'])
            continue

        existing_participant = Participant.objects.filter(
            user=member.user_profile.user,
            event=event,
        ).first()
        if existing_participant:
            intent.participant = existing_participant
            intent.status = 'completed'
            intent.note = 'User already had a participant registration for this event.'
            intent.completed_at = timezone.now()
            intent.save(update_fields=['participant', 'status', 'note', 'completed_at', 'updated_at'])
            continue

        first_specialty = member.specialties.first()
        department_name = first_specialty.name if first_specialty else 'Not specified'
        department, _ = Department.objects.get_or_create(event=event, name=department_name[:50])
        payable_amount = event.member_registration_fee or 0
        merchant_invoice_number = f"MEMEVT-{event.pk}-{member.user_profile.user_id}-{int(time.time())}"

        try:
            participant = Participant.objects.create(
                user=member.user_profile.user,
                event=event,
                registration_type='member',
                name=member.user_profile.name,
                degree=(member.position or 'Member')[:50],
                year_of_graduation=0,
                department=department,
                organization=(member.institution or 'Not provided')[:100],
                email=member.user_profile.email,
                phone=member.user_profile.phone,
                country=member.user_profile.country,
                BMDC_registration_number='',
            )
            PaymentStatus.objects.create(
                participant=participant,
                event=event,
                status='unpaid' if payable_amount else 'completed',
                amount=payable_amount,
                merchant_invoice_number=merchant_invoice_number,
            )
            intent.participant = participant
            intent.status = 'completed'
            intent.note = 'Participant registration was created after membership activation. Admin approval is still required.'
            intent.completed_at = timezone.now()
            intent.save(update_fields=['participant', 'status', 'note', 'completed_at', 'updated_at'])
        except IntegrityError as exc:
            logger.warning("Could not complete pending event intent %s: %s", intent.pk, exc)
            intent.status = 'failed'
            intent.note = 'Could not create participant because this email or phone is already registered for the event.'
            intent.save(update_fields=['status', 'note', 'updated_at'])


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
    logger.info(
        "membership_payment_completed payment_id=%s user_profile_id=%s user_profile_email=%s merchant_invoice=%s amount=%s",
        payment_record.id,
        payment_record.user_profile_id,
        payment_record.user_profile.email,
        payment_record.merchant_invoice_number,
        payment_record.amount,
    )

    # 2. Get/Activate Member
    member, created = Member.objects.get_or_create(user_profile=payment_record.user_profile)
    if member.approval_status != 'approved':
        logger.warning(
            "membership_activation_skipped_unapproved payment_id=%s member_id=%s user_profile_id=%s user_profile_email=%s approval_status=%s",
            payment_record.id,
            member.id,
            payment_record.user_profile_id,
            payment_record.user_profile.email,
            member.approval_status,
        )
        return False

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
    logger.info(
        "membership_member_activated payment_id=%s member_id=%s user_profile_email=%s membership_type_id=%s subscription_start=%s subscription_expiry=%s",
        payment_record.id,
        member.id,
        payment_record.user_profile.email,
        payment_record.membership_type_id,
        member.subscription_start_date,
        member.subscription_expiry_date,
    )
    process_pending_event_intents(member)

    # 3. Generate and Save Invoice
    try:
        invoice_path = generate_membership_invoice(payment_record)
        
        # Save path relative to MEDIA_ROOT
        relative_path = os.path.relpath(invoice_path, settings.MEDIA_ROOT)
        payment_record.invoice = relative_path
        payment_record.save()
        logger.info(
            "membership_invoice_generated payment_id=%s user_profile_email=%s invoice=%s",
            payment_record.id,
            payment_record.user_profile.email,
            relative_path,
        )
        
        # 4. Send Email
        send_membership_invoice_email(payment_record)
        logger.info(
            "membership_invoice_email_sent payment_id=%s user_profile_email=%s",
            payment_record.id,
            payment_record.user_profile.email,
        )
        queue_membership_payment_received_sms(payment_record)
        logger.info(
            "membership_payment_sms_queued payment_id=%s user_profile_email=%s",
            payment_record.id,
            payment_record.user_profile.email,
        )
        return True
    except Exception as e:
        logger.error(f"Error in automatic post-payment processing: {str(e)}")
        return False
