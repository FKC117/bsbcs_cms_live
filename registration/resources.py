from import_export import resources
from .models import Participant, AbstractSubmission, TimeSlot

#Participants resource START------------------------------------------------------------------------------#
class ParticipantResource(resources.ModelResource):
    class Meta:
        model = Participant
#Participants resource END------------------------------------------------------------------------------#

#AbstractSubmission resource START------------------------------------------------------------------------------#
class AbstractSubmissionResource(resources.ModelResource):
    class Meta:
        model = AbstractSubmission
#AbstractSubmission resource END------------------------------------------------------------------------------#
# Timeslot Model START---------------------------------------------------------------------------------#
class TimeSlotResource(resources.ModelResource):
    class Meta:
        model = TimeSlot

# Timeslot Model END---------------------------------------------------------------------------------#
# Scheduling Resources START---------------------------------------------------------------------------------#
# class SchedulingResource(resources.ModelResource):
#     class Meta:
#         model = Scheduling

from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import PaymentStatus, Participant, Event

class PaymentStatusResource(resources.ModelResource):
    participant = fields.Field(
        column_name='participant',
        attribute='participant',
        widget=ForeignKeyWidget(Participant, 'name'))  # Use 'name' instead of default 'id'

    event = fields.Field(
        column_name='event',
        attribute='event',
        widget=ForeignKeyWidget(Event, 'id'))  # Use 'id' to get the event object

    def dehydrate_event(self, payment_status):
        return f"{payment_status.event.name} - {payment_status.event.year}"

    class Meta:
        model = PaymentStatus
        fields = ('participant', 'event', 'status', 'amount', 'merchant_invoice_number', 'transaction_id', 'trxID', 'updated_at')
        export_order = fields

# Registration Kit resource START---------------------------------------------------------------------------------#
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import RegistrationKit, Event, PaymentStatus, Participant

class RegistrationKitResource(resources.ModelResource):
    event_name = fields.Field(
        column_name='event_name',
        attribute='event',
        widget=ForeignKeyWidget(Event, 'name'))
    
    event_year = fields.Field(
        column_name='event_year',
        attribute='event',
        widget=ForeignKeyWidget(Event, 'year'))
    
    participant_name = fields.Field(
        column_name='participant_name',
        attribute='payment_status',
        widget=ForeignKeyWidget(PaymentStatus, 'participant__name'))

    amount = fields.Field(
        column_name='amount',
        attribute='payment_status',
        widget=ForeignKeyWidget(PaymentStatus, 'amount'))
    
    invoice_number = fields.Field(
        column_name='invoice_number',
        attribute='payment_status',
        widget=ForeignKeyWidget(PaymentStatus, 'invoice_number'))
    
    transaction_id = fields.Field(
        column_name='transaction_id',
        attribute='payment_status',
        widget=ForeignKeyWidget(PaymentStatus, 'transaction_id'))

    payment_status = fields.Field(
        column_name='payment_status',
        attribute='payment_status',
        widget=ForeignKeyWidget(PaymentStatus, 'status'))

    registration_kit_status = fields.Field(
        column_name='registration_kit_status',
        attribute='status')

    class Meta:
        model = RegistrationKit
        fields = ('id', 'event_name', 'event_year', 'participant_name', 'amount', 'invoice_number', 'transaction_id','trxID', 'payment_status', 'registration_kit_status', 'issued_at')
        export_order = ('id', 'event_name', 'event_year', 'participant_name', 'amount', 'invoice_number', 'transaction_id','trxID', 'payment_status', 'registration_kit_status', 'issued_at')

# Registration Kit resource END---------------------------------------------------------------------------------#
