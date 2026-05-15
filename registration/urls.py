from django.conf import settings
from django.urls import path, reverse_lazy
from django.conf.urls.static import static
from . import views
from website import views as website_views
from django.contrib.auth import views as auth_views
from .views import (
    home,
    participant_list,
    participant_list_partial,
    about,
    speakers,
    registration,
    registration_submitted,
    abstract_submission,
    submission_success,
    invitation,
    schedule,
    session_detail,
    download_schedule_pdf,
    sponsor_list,
    publication_list,
    publication_detail,
    event_gallery,
    payment,
    finalize_payment,
    payment_success,
    payment_failure,
    download_abstract_book,
    event_feedback_view,
    generate_certificate,
)

app_name = 'registration'  # Define app_name

# Update URL pattern
urlpatterns = [
    # HTML sitemap for the registration/events area (shares the website sitemap view)
    path('sitemap/', website_views.sitemap_table, name='sitemap_table'),
    # URL patterns for the app.
    path('<int:event_id>/home/', views.home, name='home'),  # Ensure this path is correct

    # urls for events
    path('<int:event_id>/participants/', views.participant_list, name='participant_list'),
    path('<int:event_id>/participants/partial/', views.participant_list_partial, name='participant_list_partial'),

    path('<int:event_id>/about/', views.about, name='about'),
    path('<int:event_id>/speakers/', views.speakers, name='speakers'),
    path('<int:event_id>/registration/', views.registration, name='registration'),
    path('<int:event_id>/registration_submitted/', views.registration_submitted, name='registration_submitted'),
    path('<int:event_id>/abstract_submission/', views.abstract_submission, name='abstract_submission'),
    path('<int:event_id>/submission_success/', views.submission_success, name='submission_success'),
    path('<int:event_id>/invitation/', views.invitation, name='invitation'),
    path('<int:event_id>/schedule/', views.schedule, name='schedule'),
    path('<int:event_id>/session_detail/<int:pk>/', views.session_detail, name='session_detail'),
    path('<int:event_id>/download_schedule_pdf/', views.download_schedule_pdf, name='download_schedule_pdf'),
    path('<int:event_id>/sponsors/', views.sponsor_list, name='sponsor_list'),
    path('<int:event_id>/publication_list/', views.publication_list, name='publication_list'),
    path('<int:event_id>/publication/<int:pub_id>/', views.publication_detail, name='publication_detail'),
    # Event Gallery url
    path('<int:event_id>/gallery/', views.event_gallery, name='event_gallery'),
    # Bkash Payment url
    path('<int:event_id>/payment/<int:participant_id>/', views.payment, name='payment'), 
    path('<int:event_id>/finalize-payment/<int:participant_id>/', finalize_payment, name='finalize_payment'),
    path('<int:event_id>/payment-success/<int:participant_id>/', payment_success, name='payment_success'), 
    path('<int:event_id>/payment-failure/<int:participant_id>/', payment_failure, name='payment_failure'),

   # New Urls added here
    path('<int:event_id>/download-abstract/', views.download_abstract_book, name='download_abstract_book'),
    path('<int:event_id>/feedback/', event_feedback_view, name='event_feedback'),
    path('<int:event_id>/generate_certificate/', views.generate_certificate, name='generate_certificate')  # Corrected URL pattern
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
