from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from myApp import views
from myApp import health_views
from myApp import dashboard_views
from myApp import superadmin_views

urlpatterns = [
    # Platform health checks
    path('healthz/', health_views.healthz, name='healthz'),
    path('readyz/', health_views.readyz, name='readyz'),

    # Public-facing URLs
    path('', views.home, name='home'),
    path('start-academy/', views.start_academy, name='start_academy'),
    path('start-academy/checkout-success/', views.start_academy_checkout_success, name='start_academy_checkout_success'),
    path('webhooks/stripe/', views.stripe_webhook, name='stripe_webhook'),
    path('calculator/railway-cost/', views.railway_cost_calculator_light, name='railway_cost_calculator_light'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('courses/', views.courses, name='courses'),
    path('courses/<slug:course_slug>/', views.course_detail, name='course_detail'),
    path('courses/<slug:course_slug>/enroll/', views.enroll_course, name='enroll_course'),
    path('bundles/<int:bundle_id>/checkout/', views.create_bundle_checkout_session, name='bundle_checkout_session'),
    path('courses/<slug:course_slug>/<slug:lesson_slug>/', views.lesson_detail, name='lesson_detail'),
    path('courses/<slug:course_slug>/<slug:lesson_slug>/quiz/', views.lesson_quiz_view, name='lesson_quiz'),
    
    # Student Dashboard (Client-facing)
    path('my-dashboard/', views.student_dashboard, name='student_dashboard'),
    path('my-dashboard/course/<slug:course_slug>/', views.student_course_progress, name='student_course_progress'),
    path('my-certifications/', views.student_certifications, name='student_certifications'),
    
    # Dashboard URLs (Admin-facing, for developers)
    path('dashboard/', dashboard_views.dashboard_home, name='dashboard_home'),
    path('dashboard/analytics/', dashboard_views.dashboard_analytics, name='dashboard_analytics'),
    path('dashboard/courses/', dashboard_views.dashboard_courses, name='dashboard_courses'),
    path('dashboard/courses/add/', dashboard_views.dashboard_add_course, name='dashboard_add_course'),
    path('dashboard/api/ai-generation-status/<int:course_id>/', dashboard_views.api_ai_generation_status, name='api_ai_generation_status'),
    path('dashboard/courses/<slug:course_slug>/', dashboard_views.dashboard_course_detail, name='dashboard_course_detail'),
    path('dashboard/courses/<slug:course_slug>/delete/', dashboard_views.dashboard_delete_course, name='dashboard_delete_course'),
    path('dashboard/courses/<slug:course_slug>/lessons/', dashboard_views.dashboard_course_lessons, name='dashboard_course_lessons'),
    path('dashboard/lessons/', dashboard_views.dashboard_lessons, name='dashboard_lessons'),
    path('dashboard/lessons/add/', dashboard_views.dashboard_add_lesson, name='dashboard_add_lesson'),
    path('dashboard/lessons/upload-quiz/', dashboard_views.dashboard_upload_quiz, name='dashboard_upload_quiz'),
    path('dashboard/lessons/<int:lesson_id>/edit/', dashboard_views.dashboard_edit_lesson, name='dashboard_edit_lesson'),
    path('dashboard/lessons/<int:lesson_id>/delete/', dashboard_views.dashboard_delete_lesson, name='dashboard_delete_lesson'),
    path('dashboard/lessons/<int:lesson_id>/quiz/', dashboard_views.dashboard_lesson_quiz, name='dashboard_lesson_quiz'),
    path('dashboard/lessons/<int:lesson_id>/quiz/delete/', dashboard_views.dashboard_delete_quiz, name='dashboard_delete_quiz'),
    path('dashboard/quizzes/', dashboard_views.dashboard_quizzes, name='dashboard_quizzes'),
    
    # Student Progress Monitoring
    path('dashboard/students/', dashboard_views.dashboard_students, name='dashboard_students'),
    path('dashboard/students/progress/', dashboard_views.dashboard_student_progress, name='dashboard_student_progress'),
    path('dashboard/students/<int:user_id>/', dashboard_views.dashboard_student_detail, name='dashboard_student_detail'),
    path('dashboard/students/<int:user_id>/<slug:course_slug>/', dashboard_views.dashboard_student_detail, name='dashboard_student_detail_course'),
    path('dashboard/courses/<slug:course_slug>/progress/', dashboard_views.dashboard_course_progress, name='dashboard_course_progress'),
    
    # Bundle Management
    path('dashboard/bundles/', dashboard_views.dashboard_bundles, name='dashboard_bundles'),
    path('dashboard/bundles/add/', dashboard_views.dashboard_add_bundle, name='dashboard_add_bundle'),
    path('dashboard/bundles/<int:bundle_id>/edit/', dashboard_views.dashboard_edit_bundle, name='dashboard_edit_bundle'),
    path('dashboard/bundles/<int:bundle_id>/delete/', dashboard_views.dashboard_delete_bundle, name='dashboard_delete_bundle'),
    
    # Access Management
    path('dashboard/access/bulk/', dashboard_views.bulk_access_management, name='dashboard_bulk_access'),
    path('dashboard/access/bulk/grant/', dashboard_views.bulk_grant_access_view, name='dashboard_bulk_grant_access'),
    path('dashboard/students/<int:user_id>/grant-access/', dashboard_views.grant_course_access_view, name='dashboard_grant_access'),
    path('dashboard/students/<int:user_id>/revoke-access/', dashboard_views.revoke_course_access_view, name='dashboard_revoke_access'),
    path('dashboard/students/<int:user_id>/grant-bundle/', dashboard_views.grant_bundle_access_view, name='dashboard_grant_bundle'),
    path('dashboard/students/<int:user_id>/add-cohort/', dashboard_views.add_to_cohort_view, name='dashboard_add_cohort'),
    path('dashboard/domain-settings/', dashboard_views.dashboard_domain_settings, name='dashboard_domain_settings'),
    path('dashboard/billing/', dashboard_views.dashboard_billing, name='dashboard_billing'),
    path('dashboard/billing/portal/', dashboard_views.dashboard_billing_portal, name='dashboard_billing_portal'),
    path('dashboard/payments/stripe/connect/', dashboard_views.dashboard_connect_stripe, name='dashboard_connect_stripe'),
    path('dashboard/payments/stripe/callback/', dashboard_views.dashboard_stripe_connect_callback, name='dashboard_stripe_connect_callback'),
    path('dashboard/branding-settings/', dashboard_views.dashboard_branding_settings, name='dashboard_branding_settings'),
    path('dashboard/domain-settings/<int:domain_id>/verify/', dashboard_views.dashboard_verify_domain, name='dashboard_verify_domain'),
    path('dashboard/domain-settings/<int:domain_id>/make-primary/', dashboard_views.dashboard_make_primary_domain, name='dashboard_make_primary_domain'),
    
    # Creator/Lesson Upload Flow (kept for lesson creation)
    path('creator/', views.creator_dashboard, name='creator_dashboard'),
    path('creator/courses/<slug:course_slug>/lessons/', views.course_lessons, name='course_lessons'),
    path('creator/courses/<slug:course_slug>/add-lesson/', views.add_lesson, name='add_lesson'),
    path('creator/courses/<slug:course_slug>/lessons/<int:lesson_id>/generate/', views.generate_lesson_ai, name='generate_lesson_ai'),
    path('creator/verify-vimeo/', views.verify_vimeo_url, name='verify_vimeo_url'),
    path('creator/upload-video-transcribe/', views.upload_video_transcribe, name='upload_video_transcribe'),
    path('creator/lessons/<int:lesson_id>/transcription-status/', views.check_transcription_status, name='check_transcription_status'),
    
    # Chatbot webhook endpoint
    path('api/chatbot/', views.chatbot_webhook, name='chatbot_webhook'),
    
    # AI Chatbot endpoints
    path('api/lessons/<int:lesson_id>/train-chatbot/', views.train_lesson_chatbot, name='train_lesson_chatbot'),
    path('api/lessons/<int:lesson_id>/chatbot/', views.lesson_chatbot, name='lesson_chatbot'),
    
    # Lesson progress tracking endpoints
    path('api/lessons/<int:lesson_id>/progress/', views.update_video_progress, name='update_video_progress'),
    path('api/lessons/<int:lesson_id>/complete/', views.complete_lesson, name='complete_lesson'),
    
    # Favorite course endpoint
    path('api/courses/<int:course_id>/favorite/', views.toggle_favorite_course, name='toggle_favorite_course'),

    # Super Admin routes (platform-wide, cross-tenant)
    path('superadmin/', superadmin_views.superadmin_home, name='superadmin_home'),
    path('superadmin/tenants/', superadmin_views.superadmin_tenants, name='superadmin_tenants'),
    path('superadmin/tenants/<int:tenant_id>/', superadmin_views.superadmin_tenant_detail, name='superadmin_tenant_detail'),
    path('superadmin/tenants/<int:tenant_id>/analytics/', superadmin_views.superadmin_tenant_analytics, name='superadmin_tenant_analytics'),
    path('superadmin/analytics/', superadmin_views.superadmin_analytics, name='superadmin_analytics'),
    path('superadmin/tenants/<int:tenant_id>/suspend/', superadmin_views.superadmin_tenant_suspend, name='superadmin_tenant_suspend'),
    path('superadmin/tenants/<int:tenant_id>/admins/create/', superadmin_views.superadmin_create_tenant_admin, name='superadmin_create_tenant_admin'),
    path('superadmin/tenants/<int:tenant_id>/domains/add/', superadmin_views.superadmin_add_tenant_domain, name='superadmin_add_tenant_domain'),
    path('superadmin/tenants/<int:tenant_id>/domains/<int:domain_id>/verify/', superadmin_views.superadmin_verify_tenant_domain, name='superadmin_verify_tenant_domain'),
    path('superadmin/tenants/<int:tenant_id>/domains/<int:domain_id>/set-primary/', superadmin_views.superadmin_set_primary_tenant_domain, name='superadmin_set_primary_tenant_domain'),
    
    # Admin (optional - can be removed if not needed)
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
