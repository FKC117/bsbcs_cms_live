from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, reverse_lazy
from django.contrib.auth import views as auth_views
from django.contrib.sitemaps.views import sitemap
from django.views.generic import TemplateView, RedirectView
from registration.sitemaps import (
    EventSitemap,
    StaticViewSitemap,
    PublicationSitemap,
    WebsiteStaticSitemap,
    WebinarSitemap,
    PastEventSitemap,
)
from registration import views
from registration.views import (
    global_dashboard,
    dashboard_attention_queue,
    dashboard_event_ledger,
    dashboard_participant_preview,
    dashboard_staff_activity,
    dashboard_bulk_email_center,
    dashboard_program_session_builder,
    dashboard_program_profile_search,
    dashboard_program_profile_add,
    dashboard_program_person_remove,
)

sitemaps = {
    'events': EventSitemap,
    'static': StaticViewSitemap,
    'publications': PublicationSitemap,
    'website': WebsiteStaticSitemap,
    'webinars': WebinarSitemap,
    'past_events': PastEventSitemap,
}


urlpatterns = [
    path('admin/workflow-guide/', views.admin_workflow_guide, name='admin_workflow_guide'),
    path('admin/', admin.site.urls),
    path('dashboard/', global_dashboard, name='global_dashboard'),
    path('dashboard/attention-queue/', dashboard_attention_queue, name='dashboard_attention_queue'),
    path('dashboard/event-ledger/', dashboard_event_ledger, name='dashboard_event_ledger'),
    path('dashboard/participant-preview/', dashboard_participant_preview, name='dashboard_participant_preview'),
    path('dashboard/staff-activity/', dashboard_staff_activity, name='dashboard_staff_activity'),
    path('dashboard/bulk-email-center/', dashboard_bulk_email_center, name='dashboard_bulk_email_center'),
    path('dashboard/program-session-builder/', dashboard_program_session_builder, name='dashboard_program_session_builder'),
    path('dashboard/program-session-builder/profile-search/', dashboard_program_profile_search, name='dashboard_program_profile_search'),
    path('dashboard/program-session-builder/profile-add/', dashboard_program_profile_add, name='dashboard_program_profile_add'),
    path('dashboard/program-session-builder/person-remove/', dashboard_program_person_remove, name='dashboard_program_person_remove'),
    path('', include(('website.urls', 'website'), namespace='website')),
    path('index/', views.index, name='index'),

    path('create-profile/', views.create_profile,name='create_profile'),
    path('corporate-access/', views.corporate_account_request, name='corporate_account_request'),
    path('corporate-access/received/', views.corporate_account_request_done, name='corporate_account_request_done'),
    path('corporate/login/', views.corporate_login, name='corporate_login'),
    path('corporate/dashboard/', views.corporate_dashboard, name='corporate_dashboard'),
    path('corporate/events/<int:event_id>/registration/', views.corporate_event_registration, name='corporate_event_registration'),
    path('corporate/events/<int:event_id>/template.csv', views.corporate_event_template_csv, name='corporate_event_template_csv'),
    path('corporate/payments/<int:payment_id>/', views.corporate_payment, name='corporate_payment'),
    path('corporate/payments/<int:payment_id>/invoice/', views.corporate_payment_invoice, name='corporate_payment_invoice'),
    path('corporate/payments/<int:payment_id>/success/', views.corporate_payment_success, name='corporate_payment_success'),
    path('corporate/payments/<int:payment_id>/finalize/', views.corporate_finalize_payment, name='corporate_finalize_payment'),
    path('corporate/payments/<int:payment_id>/failure/', views.corporate_payment_failure, name='corporate_payment_failure'),
    path('event/', include(('registration.urls', 'registration'), namespace='registration')),

    path('profile/', views.user_profile, name='user_profile'),

    #universal login system
    path('accounts/login/', views.user_login, name='login'),  # Universal login
    path('accounts/logout/', views.user_logout, name='logout'),  # Universal logout
    path('accounts/password_change/', views.CustomPasswordChangeView.as_view(), name='password_change'),  # Universal password change
    path('accounts/password_change/done/', auth_views.PasswordChangeDoneView.as_view(template_name='password_change_done.html'), name='password_change_done'),  # Universal password change done
    path('accounts/password_reset/', views.CustomPasswordResetView.as_view(), name='password_reset'),  # Universal password reset
    path('accounts/password_reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='password_reset_done.html'), name='password_reset_done'),  # Universal password reset done
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='password_reset_confirm.html', success_url=reverse_lazy('password_reset_complete')), name='password_reset_confirm'),  # Universal password reset confirm
    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='password_reset_complete.html'), name='password_reset_complete'),  # Universal password reset complete
    #Bkash Payment Urls
    # path('initiate-payment/<int:event_id>/', initiate_payment, name='initiate_payment'),
    # path('payment-success/', payment_success, name='payment_success'),
    # path('payment-failure/', payment_failure, name='payment_failure'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain'), name='robots_txt'),
    path('favicon.ico', RedirectView.as_view(url='/media/site_settings/favicon.ico', permanent=True)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
