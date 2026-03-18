from django.contrib import admin
from .models import (
    Tenant, TenantConfig, TenantMembership, TenantDomain,
    Course, CourseResource, Module, Lesson, UserProgress, CourseEnrollment, Exam, ExamAttempt, Certification,
    Cohort, CohortMember, Bundle, BundlePurchase, CourseAccess, LearningPath, LearningPathCourse
)


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'custom_domain', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'slug', 'custom_domain']


@admin.register(TenantConfig)
class TenantConfigAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'chatbot_webhook', 'vimeo_team_id', 'accredible_issuer_id', 'updated_at']
    search_fields = ['tenant__name', 'tenant__slug', 'chatbot_webhook']


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'user', 'role', 'is_active', 'updated_at']
    list_filter = ['tenant', 'role', 'is_active']
    search_fields = ['tenant__name', 'tenant__slug', 'user__username', 'user__email']


@admin.register(TenantDomain)
class TenantDomainAdmin(admin.ModelAdmin):
    list_display = ['domain', 'tenant', 'is_temporary', 'is_primary', 'is_verified', 'updated_at']
    list_filter = ['is_temporary', 'is_primary', 'is_verified', 'tenant']
    search_fields = ['domain', 'tenant__name', 'tenant__slug']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['name', 'course_type', 'status', 'coach_name', 'is_subscribers_only', 'created_at']
    list_filter = ['course_type', 'status', 'is_subscribers_only', 'is_accredible_certified']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'course', 'order']
    list_filter = ['course']
    ordering = ['course', 'order']


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'module', 'order', 'lesson_type', 'video_duration', 'ai_generation_status']
    list_filter = ['course', 'lesson_type', 'ai_generation_status']
    search_fields = ['title', 'description', 'working_title', 'vimeo_id']
    prepopulated_fields = {'slug': ('title',)}
    ordering = ['course', 'order']
    fieldsets = (
        ('Basic Information', {
            'fields': ('course', 'module', 'title', 'slug', 'order', 'lesson_type')
        }),
        ('Video', {
            'fields': ('video_url', 'vimeo_url', 'vimeo_id', 'vimeo_thumbnail', 'vimeo_duration_seconds', 'video_duration', 'google_drive_url', 'google_drive_id')
        }),
        ('Lesson Creation', {
            'fields': ('working_title', 'rough_notes')
        }),
        ('AI Generated Content', {
            'fields': ('ai_generation_status', 'ai_clean_title', 'ai_short_summary', 'ai_full_description', 'ai_outcomes', 'ai_coach_actions')
        }),
        ('Resources', {
            'fields': ('description', 'workbook_url', 'resources_url')
        }),
    )


@admin.register(UserProgress)
class UserProgressAdmin(admin.ModelAdmin):
    list_display = ['user', 'lesson', 'status', 'completed', 'video_watch_percentage', 'progress_percentage', 'last_accessed']
    list_filter = ['status', 'completed', 'last_accessed']
    search_fields = ['user__username', 'lesson__title']
    readonly_fields = ['last_accessed', 'started_at', 'completed_at']


@admin.register(CourseResource)
class CourseResourceAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'resource_type', 'created_at']
    list_filter = ['resource_type', 'course']
    search_fields = ['title', 'description', 'course__name']
    ordering = ['course', 'order', 'id']


@admin.register(CourseEnrollment)
class CourseEnrollmentAdmin(admin.ModelAdmin):
    list_display = ['user', 'course', 'payment_type', 'enrolled_at']
    list_filter = ['payment_type', 'enrolled_at']
    search_fields = ['user__username', 'course__name']


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ['course', 'title', 'passing_score', 'max_attempts', 'is_active']
    list_filter = ['is_active']
    search_fields = ['course__name', 'title']


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ['user', 'exam', 'score', 'passed', 'started_at', 'completed_at', 'attempt_number']
    list_filter = ['passed', 'started_at', 'exam']
    search_fields = ['user__username', 'exam__course__name']
    readonly_fields = ['started_at', 'attempt_number']
    
    def attempt_number(self, obj):
        return obj.attempt_number()
    attempt_number.short_description = 'Attempt #'


@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'course', 'status', 'issued_at', 'accredible_certificate_id']
    list_filter = ['status', 'issued_at']
    search_fields = ['user__username', 'course__name', 'accredible_certificate_id']
    readonly_fields = ['created_at', 'updated_at']


# ========== ACCESS CONTROL ADMIN ==========

@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'get_member_count', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(CohortMember)
class CohortMemberAdmin(admin.ModelAdmin):
    list_display = ['user', 'cohort', 'joined_at', 'remove_access_on_leave']
    list_filter = ['cohort', 'joined_at', 'remove_access_on_leave']
    search_fields = ['user__username', 'cohort__name']


@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    list_display = ['name', 'bundle_type', 'is_active', 'price', 'get_course_count', 'created_at']
    list_filter = ['bundle_type', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ['courses']
    
    def get_course_count(self, obj):
        return obj.courses.count()
    get_course_count.short_description = 'Courses'


@admin.register(BundlePurchase)
class BundlePurchaseAdmin(admin.ModelAdmin):
    list_display = ['user', 'bundle', 'purchase_id', 'purchase_date']
    list_filter = ['bundle', 'purchase_date']
    search_fields = ['user__username', 'bundle__name', 'purchase_id']
    filter_horizontal = ['selected_courses']
    readonly_fields = ['purchase_date']


@admin.register(CourseAccess)
class CourseAccessAdmin(admin.ModelAdmin):
    list_display = ['user', 'course', 'access_type', 'status', 'get_source', 'granted_at', 'expires_at']
    list_filter = ['access_type', 'status', 'granted_at', 'expires_at']
    search_fields = ['user__username', 'course__name', 'purchase_id']
    readonly_fields = ['granted_at', 'revoked_at']
    fieldsets = (
        ('Access Information', {
            'fields': ('user', 'course', 'access_type', 'status')
        }),
        ('Source', {
            'fields': ('bundle_purchase', 'cohort', 'purchase_id', 'granted_by')
        }),
        ('Dates', {
            'fields': ('granted_at', 'expires_at', 'revoked_at', 'revoked_by', 'revocation_reason')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
    )
    
    def get_source(self, obj):
        return obj.get_source_display()
    get_source.short_description = 'Source'


@admin.register(LearningPath)
class LearningPathAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'get_course_count', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    
    def get_course_count(self, obj):
        return obj.courses.count()
    get_course_count.short_description = 'Courses'


@admin.register(LearningPathCourse)
class LearningPathCourseAdmin(admin.ModelAdmin):
    list_display = ['learning_path', 'course', 'order', 'is_required']
    list_filter = ['learning_path', 'is_required']
    search_fields = ['learning_path__name', 'course__name']
    ordering = ['learning_path', 'order']
