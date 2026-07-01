from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Participant, PaymentStatus, RegistrationKit
from .views import ensure_participant_chest_card_generated


@receiver(post_save, sender=PaymentStatus)
def create_registration_kit(sender, instance, created, **kwargs):
    if instance.status in ['paid', 'completed']:
        RegistrationKit.objects.get_or_create(
            event=instance.event,
            payment_status=instance,
            defaults={'status': 'not_issued'}
        )

    if created:
        print(f"Registration kit created for {instance.participant.name} - {instance.event.name}")
    else:
        print(f"Registration kit already exists for {instance.participant.name} - {instance.event.name}")

    if instance.participant_id:
        transaction.on_commit(lambda: _auto_generate_chest_card(instance.participant_id))


@receiver(post_save, sender=Participant)
def auto_generate_chest_card_after_approval(sender, instance, **kwargs):
    transaction.on_commit(lambda: _auto_generate_chest_card(instance.id))


def _auto_generate_chest_card(participant_id):
    try:
        participant = Participant.objects.select_related('event').filter(pk=participant_id).first()
        if participant:
            ensure_participant_chest_card_generated(participant, request=None)
    except Exception as exc:
        print(f"Chest card auto-generation skipped for participant {participant_id}: {exc}")
