from django.urls import path
from . import views

urlpatterns = [
    path('', views.homepage, name='homepage'),
    # Alias so /homepage also works (keeps root '' as primary)
    path('homepage/', views.homepage, name='homepage_alias'),
    path('about/', views.about, name='about'),
    path('knowledge-center/', views.knowledge_center, name='knowledge_center'),
    path('member-directory/', views.member_directory, name='member_directory'),
    path('membership-form/', views.membership_form, name='membership_form'),
    # Expose events at /events/ and use URL name 'events'
    path('events/', views.events, name='events'),
    path('media-gallery/', views.media_gallery, name='media_gallery'),
    path('research-and-publications/', views.research_and_publications, name='research_and_publications'),
    path('past-events/', views.past_events_list, name='past_events_list'),
    path('past-events/<slug:slug>/', views.past_event_detail, name='past_event_detail'),
    path('webinars/', views.webinars, name='webinars'),
    path('webinars/<int:pk>/', views.webinar_detail, name='webinar_detail'),
    path('favicon.ico', views.favicon),
    # Membership Subscription URLs
    path('membership/pay/', views.membership_payment_init, name='membership_payment_init'),
    path('membership/payment-callback/', views.membership_payment_callback, name='membership_payment_callback'),
    path('membership/payment-finalize/', views.membership_payment_finalize, name='membership_payment_finalize'),

    # HTML sitemap for human visitors
    path('sitemap/', views.sitemap_table, name='sitemap_table'),
]