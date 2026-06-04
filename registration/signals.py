from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import PaymentStatus, RegistrationKit

@receiver(post_save, sender=PaymentStatus)
def create_registration_kit(sender, instance, created, **kwargs):
    # Completed is the successful payment state used by the current payment flow.
    if instance.status == 'completed':
        RegistrationKit.objects.get_or_create(
            event=instance.event,  # Link to the event
            payment_status=instance,
            defaults={'status': 'not_issued'}
        )

    if created:
        print(f"Registration kit created for {instance.participant.name} - {instance.event.name}")
    else:
        print(f"Registration kit already exists for {instance.participant.name} - {instance.event.name}")
