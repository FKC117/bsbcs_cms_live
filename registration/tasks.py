from celery import shared_task

from .bulk_email_services import send_pending_bulk_email_recipients


@shared_task(bind=True)
def send_pending_bulk_email_campaign(self, bulk_email_id, sent_by_user_id=None):
    return send_pending_bulk_email_recipients(
        bulk_email_id=bulk_email_id,
        sent_by_user_id=sent_by_user_id,
    )
