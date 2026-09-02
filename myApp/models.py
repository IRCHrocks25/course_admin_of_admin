from django.db import models
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.utils import timezone
import json
import re


class Tenant(models.Model):
    """White-label tenant/account boundary."""
    BILLING_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('past_due', 'Past Due'),
        ('canceled', 'Canceled'),
    ]

    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    custom_domain = models.CharField(max_length=255, unique=True, null=True, blank=True)
    logo = models.ImageField(upload_to='tenant_logos/', null=True, blank=True)
    primary_color = models.CharField(max_length=7, default='#3B82F6')
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    plan_code = models.CharField(max_length=50, blank=True, default='starter')
    billing_status = models.CharField(max_length=20, choices=BILLING_STATUS_CHOICES, default='active')
    stripe_customer_id = models.CharField(max_length=120, blank=True, default='')
    stripe_subscription_id = models.CharField(max_length=120, blank=True, default='')
    setup_fee_paid = models.BooleanField(default=False)
    # GHL (GoHighLevel) integration opt-in. Default off; connecting via OAuth
    # flips this true. All GHL UI, webhooks, sync jobs and API calls gate on it.
    ghl_enabled = models.BooleanField(default=False)
    referral_code = models.CharField(max_length=24, unique=True, blank=True, default='')
    referred_by = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='referred_tenants'
    )
    referral_recorded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def _generate_referral_code(self):
        # Stable, readable code based on slug/name + random suffix.
        seed_source = (self.slug or self.name or 'tenant').upper()
        seed = re.sub(r'[^A-Z0-9]', '', seed_source)[:6] or 'TENANT'
        charset = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        for _ in range(15):
            suffix = get_random_string(6, allowed_chars=charset)
            candidate = f"{seed}-{suffix}"
            existing = Tenant.objects.filter(referral_code=candidate)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if not existing.exists():
                return candidate
        # Very unlikely fallback.
        return f"TENANT-{get_random_string(8, allowed_chars=charset)}"

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = self._generate_referral_code()
        super().save(*args, **kwargs)


class TenantConfig(models.Model):
    """Tenant-level integration and feature configuration."""
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='config')
    chatbot_webhook = models.URLField(blank=True)
    registration_webhook = models.URLField(
        blank=True,
        help_text="Katalyst CRM webhook URL. POSTed when a student self-registers. Leave blank to disable.",
    )
    vimeo_team_id = models.CharField(max_length=255, blank=True)
    accredible_issuer_id = models.CharField(max_length=255, blank=True)
    stripe_connect_account_id = models.CharField(max_length=120, blank=True)
    stripe_connect_onboarding_complete = models.BooleanField(default=False)
    stripe_connect_charges_enabled = models.BooleanField(default=False)
    # Own-keys mode: tenant supplies their own Stripe credentials directly.
    stripe_own_secret_key = models.CharField(max_length=255, blank=True)
    stripe_own_publishable_key = models.CharField(max_length=255, blank=True)
    stripe_own_webhook_secret = models.CharField(max_length=255, blank=True)
    features = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tenant Config"
        verbose_name_plural = "Tenant Configs"

    def __str__(self):
        return f"Config for {self.tenant.name}"


class TenantDomain(models.Model):
    """Domain records for tenant routing (temporary + custom domains)."""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='domains')
    domain = models.CharField(max_length=255, unique=True)
    is_temporary = models.BooleanField(default=False, help_text="System-provided temporary subdomain")
    is_primary = models.BooleanField(default=False, help_text="Primary public domain for this tenant")
    is_verified = models.BooleanField(default=False, help_text="Whether DNS/ownership is verified")
    verification_notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_primary', 'domain']
        unique_together = ['tenant', 'domain']
        indexes = [
            models.Index(fields=['tenant', 'is_primary', 'is_verified']),
        ]

    def __str__(self):
        return f"{self.domain} ({self.tenant.slug})"

class Course(models.Model):
    COURSE_TYPES = [
        ('sprint', 'Sprint'),
        ('speaking', 'Speaking'),
        ('consultancy', 'Consultancy'),
        ('special', 'Special'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('locked', 'Locked'),
        ('coming_soon', 'Coming Soon'),
    ]
    
    name = models.CharField(max_length=200)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='courses', null=True, blank=True)
    slug = models.SlugField(max_length=200)
    category = models.CharField(max_length=120, null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0, help_text="Lower numbers appear first in course listings.")
    course_type = models.CharField(max_length=20, choices=COURSE_TYPES, default='sprint')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    description = models.TextField()
    short_description = models.CharField(max_length=1000)
    thumbnail = models.ImageField(upload_to='course_thumbnails/', null=True, blank=True)
    coach_name = models.CharField(max_length=100, default='Sprint Coach')
    is_subscribers_only = models.BooleanField(default=False)
    is_accredible_certified = models.BooleanField(default=False)
    has_asset_templates = models.BooleanField(default=False)
    exam_unlock_days = models.IntegerField(default=120, help_text="Days after enrollment before exam unlocks")
    special_tag = models.CharField(max_length=100, blank=True, help_text="e.g., 'Black Friday 2025 Special'")
    
    # Course Availability & Access Rules
    VISIBILITY_CHOICES = [
        ('public', 'Public (visible to anyone)'),
        ('members_only', 'Members Only (visible to logged-in users)'),
        ('hidden', 'Hidden (not in catalog, direct link only)'),
        ('private', 'Private (manual assignment only)'),
    ]
    
    ENROLLMENT_METHOD_CHOICES = [
        ('open', 'Open Enrollment (free/lead magnet)'),
        ('purchase', 'Purchase Required'),
        ('invite_only', 'Invite/Assigned Only'),
        ('cohort_only', 'Cohort Only'),
        ('subscription_only', 'Subscription Only'),
    ]
    
    ACCESS_DURATION_CHOICES = [
        ('lifetime', 'Lifetime Access'),
        ('fixed_days', 'Fixed Duration (days)'),
        ('until_date', 'Access Until Date'),
        ('drip', 'Drip Schedule'),
    ]
    
    price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Leave blank or 0 for free. Set a price to require purchase.")
    member_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Discounted price for active members. Blank means members pay the regular price.",
    )
    included_in_membership = models.BooleanField(
        default=True,
        help_text="If off, an active membership does NOT unlock this course; it must be purchased separately.",
    )
    grants_membership_months = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="If set, purchasing this course grants this many months of complimentary membership.",
    )
    grants_membership_tier = models.ForeignKey(
        'MembershipTier', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='comp_granting_courses',
        help_text="Tier the complimentary grant targets. Blank grants all-access (whole catalog).",
    )
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default='public', help_text="Who can see this course exists")
    enrollment_method = models.CharField(max_length=20, choices=ENROLLMENT_METHOD_CHOICES, default='open', help_text="How students get access")
    access_duration_type = models.CharField(max_length=20, choices=ACCESS_DURATION_CHOICES, default='lifetime', help_text="Access duration rule")
    access_duration_days = models.IntegerField(null=True, blank=True, help_text="Fixed duration in days (if access_duration_type='fixed_days')")
    access_until_date = models.DateTimeField(null=True, blank=True, help_text="Access expires on this date (if access_duration_type='until_date')")
    prerequisite_courses = models.ManyToManyField('self', symmetrical=False, blank=True, related_name='unlocks_courses', help_text="Courses that must be completed first")
    required_quiz_score = models.IntegerField(null=True, blank=True, help_text="Required quiz score to unlock (0-100)")

    # Guided CourseForge wizard + AI context (steps 1–5); empty for legacy courses
    creation_blueprint = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'slug'], name='uniq_course_tenant_slug')
        ]
    
    def __str__(self):
        return self.name
    
    def get_lesson_count(self):
        return self.lessons.count()
    
    def get_user_progress(self, user):
        if not user.is_authenticated:
            return 0
        completed = UserProgress.objects.filter(user=user, lesson__course=self, completed=True).count()
        total = self.lessons.count()
        if total == 0:
            return 0
        return int((completed / total) * 100)


# Deterministic accent palette for category "initial" tiles when no thumbnail is set.
CATEGORY_ACCENT_COLORS = [
    '#1a6bff', '#7c3aed', '#0891b2', '#db2777',
    '#ea580c', '#16a34a', '#d97706', '#4f46e5',
]


def category_accent_color(name):
    """Pick a stable accent color for a category name (used for the initial tile)."""
    key = (name or '').strip().lower()
    if not key:
        return CATEGORY_ACCENT_COLORS[0]
    total = sum(ord(ch) for ch in key)
    return CATEGORY_ACCENT_COLORS[total % len(CATEGORY_ACCENT_COLORS)]


def category_initial(name):
    """First alphanumeric character of a category name, uppercased (fallback '#')."""
    for ch in (name or '').strip():
        if ch.isalnum():
            return ch.upper()
    return '#'


def sort_category_names(names, order_map):
    """Sort category names by their saved display order, then alphabetically.

    ``order_map`` maps lowercased category name -> display_order (see
    ``CourseCategory.order_map_for_tenant``). Categories with a saved order come
    first (in that order); categories without one fall back to alphabetical so a
    tenant that never set an order keeps today's A-Z behaviour. "Uncategorized"
    (and blank) always sorts last.
    """
    def key(name):
        clean = (name or '').strip().lower()
        if clean in ('', 'uncategorized'):
            return (2, 0, clean)
        order = order_map.get(clean)
        if order is None:
            return (1, 0, clean)
        return (0, order, clean)
    return sorted(names, key=key)


class CourseCategory(models.Model):
    """
    Display metadata for a course category.

    Categories themselves remain free text on ``Course.category``; this model
    only decorates a category name (within a tenant) with an optional thumbnail
    so the catalog can render an image instead of a generic folder icon.
    """
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='course_categories', null=True, blank=True)
    name = models.CharField(max_length=120)
    thumbnail = models.ImageField(upload_to='category_thumbnails/', null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Course category'
        verbose_name_plural = 'Course categories'
        ordering = ['display_order', 'name']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'name'], name='uniq_course_category_tenant_name')
        ]

    def __str__(self):
        return self.name

    @classmethod
    def thumbnail_map_for_tenant(cls, tenant):
        """Return {lowercased category name: thumbnail url} for a tenant."""
        qs = cls.objects.all()
        if tenant is not None:
            qs = qs.filter(tenant=tenant)
        result = {}
        for category in qs:
            if not category.thumbnail:
                continue
            try:
                result[category.name.strip().lower()] = category.thumbnail.url
            except Exception:
                continue
        return result

    @classmethod
    def order_map_for_tenant(cls, tenant):
        """Return {lowercased category name: display_order} for a tenant."""
        qs = cls.objects.all()
        if tenant is not None:
            qs = qs.filter(tenant=tenant)
        result = {}
        for category in qs.values_list('name', 'display_order'):
            name, order = category
            result[(name or '').strip().lower()] = order
        return result


class CourseResource(models.Model):
    """Downloadable resources for a course (SOP templates, checklists, PDFs, etc.)"""
    RESOURCE_TYPES = [
        ('template', 'Template'),
        ('checklist', 'Checklist'),
        ('pdf', 'PDF Document'),
        ('workbook', 'Workbook'),
        ('other', 'Other'),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='course_resources', null=True, blank=True)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='resources')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    resource_type = models.CharField(max_length=20, choices=RESOURCE_TYPES, default='other')
    # Either upload a file OR provide a URL (e.g. Google Drive, Dropbox).
    # New uploads go to Iceberg and are stored in file_url; file is legacy/local only.
    file = models.FileField(upload_to='course_resources/', blank=True, null=True)
    file_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="Iceberg CDN URL or external link (Google Drive, etc.)",
    )
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.title} - {self.course.name}"

    def get_download_url(self):
        """Return the URL to download this resource (file or external link)"""
        if self.file:
            return self.file.url
        return self.file_url


class CourseTranslation(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('approved', 'Approved'),
    ]
    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('ai', 'AI'),
    ]

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='translations')
    language_code = models.CharField(max_length=10)
    name = models.CharField(max_length=200, blank=True, default='')
    description = models.TextField(blank=True, default='')
    short_description = models.CharField(max_length=1000, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    translation_source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('course', 'language_code')]
        ordering = ['language_code']

    def __str__(self):
        return f"{self.course.name} [{self.language_code}]"


class Module(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='modules', null=True, blank=True)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='modules')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['order', 'id']
    
    def __str__(self):
        return f"{self.course.name} - {self.name}"


class ModuleTranslation(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('approved', 'Approved'),
    ]
    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('ai', 'AI'),
    ]

    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='translations')
    language_code = models.CharField(max_length=10)
    name = models.CharField(max_length=200, blank=True, default='')
    description = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    translation_source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('module', 'language_code')]
        ordering = ['language_code']

    def __str__(self):
        return f"{self.module.name} [{self.language_code}]"


class Lesson(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='lessons', null=True, blank=True)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='lessons')
    module = models.ForeignKey(Module, on_delete=models.SET_NULL, null=True, blank=True, related_name='lessons')
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    description = models.TextField()
    video_url = models.URLField(blank=True)
    video_duration = models.IntegerField(default=0, help_text="Duration in minutes")
    order = models.IntegerField(default=0)
    workbook_url = models.URLField(blank=True)
    resources_url = models.URLField(blank=True)
    lesson_type = models.CharField(max_length=50, default='video', choices=[
        ('video', 'Video'),
        ('live', 'Live Session'),
        ('replay', 'Replay'),
    ])
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Vimeo Integration Fields
    vimeo_url = models.URLField(blank=True, help_text="Full Vimeo URL (e.g., https://vimeo.com/123456789)")
    vimeo_id = models.CharField(max_length=50, blank=True, help_text="Vimeo video ID extracted from URL")
    vimeo_thumbnail = models.URLField(blank=True, help_text="Vimeo thumbnail URL")
    vimeo_duration_seconds = models.IntegerField(default=0, help_text="Duration in seconds from Vimeo")
    
    # Google Drive Integration Fields
    google_drive_url = models.URLField(blank=True, help_text="Google Drive video embed URL")
    google_drive_id = models.CharField(max_length=200, blank=True, help_text="Google Drive file ID")
    
    # Lesson Creation Fields
    working_title = models.CharField(max_length=200, blank=True, help_text="Rough title before AI generation")
    rough_notes = models.TextField(blank=True, help_text="Optional notes or outline for AI")
    
    # Transcription Fields
    # Note: Video files are NOT saved to the database - they are only used temporarily for transcription
    transcription = models.TextField(blank=True, help_text="Auto-generated transcription from video")
    transcription_status = models.CharField(max_length=20, default='pending', choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ])
    transcription_error = models.TextField(blank=True, help_text="Error message if transcription fails")
    
    # AI Generated Content
    ai_generation_status = models.CharField(max_length=20, default='pending', choices=[
        ('pending', 'Pending'),
        ('generated', 'Generated'),
        ('approved', 'Approved'),
    ])
    ai_clean_title = models.CharField(max_length=200, blank=True, help_text="AI-generated polished title")
    ai_short_summary = models.TextField(blank=True, help_text="AI-generated short summary for lesson list")
    ai_full_description = models.TextField(blank=True, help_text="AI-generated full description for student page")
    ai_outcomes = models.JSONField(default=list, blank=True, help_text="List of outcomes this lesson will produce")
    ai_coach_actions = models.JSONField(default=list, blank=True, help_text="Recommended AI Coach actions for this lesson")
    ai_hero_image_url = models.URLField(
        blank=True, default='',
        help_text="Cloudinary URL of the AI-generated hero image for this lesson"
    )
    ai_hero_image_prompt = models.TextField(
        blank=True, default='',
        help_text="The DALL-E prompt used to generate the hero image"
    )
    generation_settings = models.JSONField(default=dict, blank=True, help_text="LessonGenerationSettings dict captured at last AI generation")

    # Editor.js Content
    content = models.JSONField(default=dict, blank=True, help_text="Editor.js content blocks for lesson content")

    # Student page section visibility (video-only lessons can hide text containers)
    show_what_youll_learn = models.BooleanField(
        default=True,
        help_text='Show the "What You\'ll Learn Today" section on the student lesson page',
    )
    show_lesson_notes = models.BooleanField(
        default=True,
        help_text='Show the "Lesson Notes" section on the student lesson page',
    )
    
    # AI Chatbot Integration Fields
    ai_chatbot_enabled = models.BooleanField(default=False, help_text="Whether AI chatbot is enabled for this lesson")
    ai_chatbot_webhook_id = models.CharField(max_length=200, blank=True, help_text="Chatbot webhook ID from training")
    ai_chatbot_trained_at = models.DateTimeField(null=True, blank=True, help_text="When transcript was sent for training")
    ai_chatbot_training_status = models.CharField(
        max_length=20, 
        default='pending', 
        choices=[
            ('pending', 'Pending'),
            ('training', 'Training'),
            ('trained', 'Trained'),
            ('failed', 'Failed'),
        ],
        help_text="Status of AI training"
    )
    ai_chatbot_training_error = models.TextField(blank=True, help_text="Error message if training fails")

    # AI Audio Narration Fields (OpenAI TTS -> Cloudinary)
    audio_url = models.URLField(blank=True, default='', help_text="Public URL of the AI-narrated MP3 for this lesson")
    audio_status = models.CharField(max_length=20, default='pending', choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ], help_text="Status of AI audio narration generation")
    audio_error = models.TextField(blank=True, default='', help_text="Error message if audio generation fails")
    audio_duration_seconds = models.IntegerField(default=0, help_text="Duration of the narration MP3 in seconds")

    class Meta:
        ordering = ['order', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'course', 'slug'],
                name='uniq_lesson_tenant_course_slug'
            )
        ]
    
    def __str__(self):
        return f"{self.course.name} - {self.title}"
    
    def get_vimeo_embed_url(self):
        """Convert Vimeo URL/id to embed format with URL fallback."""
        if self.vimeo_id:
            return f"https://player.vimeo.com/video/{self.vimeo_id}"

        # Backfill-safe fallback for legacy records that only stored vimeo_url.
        raw_url = (self.vimeo_url or '').strip()
        if raw_url:
            match = re.search(
                r'(?:vimeo\.com/(?:video/|channels/[^/]+/|groups/[^/]+/videos/|album/\d+/video/|ondemand/[^/]+/|manage/videos/)?|player\.vimeo\.com/video/)(\d+)',
                raw_url,
            )
            if match:
                return f"https://player.vimeo.com/video/{match.group(1)}"
        return ""
    
    def get_video_embed_url(self):
        """Convert video_url to embed format. YouTube watch/short URLs must use embed format for iframes."""
        url = (self.video_url or '').strip()
        if not url:
            return ''
        # YouTube: watch URL or youtu.be short URL -> embed
        yt_watch = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
        if yt_watch:
            return f"https://www.youtube.com/embed/{yt_watch.group(1)}"
        # Already embed or other URL - use as-is
        return url
    
    def get_formatted_duration(self):
        """Format duration in MM:SS format"""
        if self.vimeo_duration_seconds:
            minutes = self.vimeo_duration_seconds // 60
            seconds = self.vimeo_duration_seconds % 60
            return f"{minutes}:{seconds:02d}"
        elif self.video_duration:
            return f"{self.video_duration}:00"
        return "Not set"

    def get_audio_duration_display(self):
        """Format audio narration duration in MM:SS format, or '' if unknown."""
        if self.audio_duration_seconds:
            minutes = self.audio_duration_seconds // 60
            seconds = self.audio_duration_seconds % 60
            return f"{minutes}:{seconds:02d}"
        return ""
    
    def get_outcomes_list(self):
        """Return outcomes as a list"""
        if isinstance(self.ai_outcomes, list):
            return self.ai_outcomes
        if isinstance(self.ai_outcomes, str):
            try:
                return json.loads(self.ai_outcomes)
            except:
                return []
        return []
    
    def get_coach_actions_list(self):
        """Return coach actions as a list"""
        if isinstance(self.ai_coach_actions, list):
            return self.ai_coach_actions
        if isinstance(self.ai_coach_actions, str):
            try:
                return json.loads(self.ai_coach_actions)
            except:
                return []
        return []


class LessonTranslation(models.Model):
    """Localized lesson content. English remains on Lesson; this table is optional per language."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('generated', 'Generated'),
        ('approved', 'Approved'),
        ('published', 'Published'),
    ]
    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('ai', 'AI'),
    ]

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='translations')
    language_code = models.CharField(max_length=10, help_text="ISO 639-1/639-2 code, e.g. it, fil, es")
    title = models.CharField(max_length=200, blank=True, default='')
    description = models.TextField(blank=True, default='')
    ai_clean_title = models.CharField(max_length=200, blank=True, default='')
    ai_short_summary = models.TextField(blank=True, default='')
    ai_full_description = models.TextField(blank=True, default='')
    ai_outcomes = models.JSONField(default=list, blank=True)
    ai_coach_actions = models.JSONField(default=list, blank=True)
    content = models.JSONField(default=dict, blank=True, help_text="Editor.js content blocks")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    translation_source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    audio_url = models.URLField(blank=True, default='')
    audio_status = models.CharField(max_length=20, default='pending', choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ])
    audio_duration_seconds = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('lesson', 'language_code')]
        ordering = ['language_code']

    def __str__(self):
        return f"{self.lesson.title} [{self.language_code}]"

    def get_outcomes_list(self):
        if isinstance(self.ai_outcomes, list):
            return self.ai_outcomes
        if isinstance(self.ai_outcomes, str):
            try:
                return json.loads(self.ai_outcomes)
            except Exception:
                return []
        return []

    def get_coach_actions_list(self):
        if isinstance(self.ai_coach_actions, list):
            return self.ai_coach_actions
        if isinstance(self.ai_coach_actions, str):
            try:
                return json.loads(self.ai_coach_actions)
            except Exception:
                return []
        return []


class LessonQuiz(models.Model):
    """Optional quiz that can be attached to a lesson."""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='lesson_quizzes', null=True, blank=True)
    lesson = models.OneToOneField(Lesson, on_delete=models.CASCADE, related_name='quiz')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_required = models.BooleanField(default=False, help_text="If true, quiz must be passed to complete the lesson. Defaults to optional so quizzes never block progression unless an admin opts in.")
    passing_score = models.IntegerField(default=70, help_text="Score percentage required to pass (0–100)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['lesson__order', 'lesson__id']

    def __str__(self):
        return f"Quiz for {self.lesson.title}"


class LessonQuizQuestion(models.Model):
    """Multiple‑choice question for a lesson quiz."""
    OPTION_CHOICES = [
        ('A', 'Option A'),
        ('B', 'Option B'),
        ('C', 'Option C'),
        ('D', 'Option D'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='lesson_quiz_questions', null=True, blank=True)
    quiz = models.ForeignKey(LessonQuiz, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField()
    option_a = models.CharField(max_length=300)
    option_b = models.CharField(max_length=300)
    option_c = models.CharField(max_length=300, blank=True)
    option_d = models.CharField(max_length=300, blank=True)
    correct_option = models.CharField(max_length=1, choices=OPTION_CHOICES)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"Q{self.order} for {self.quiz.lesson.title}"


class LessonQuizTranslation(models.Model):
    """Localized quiz title and description."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('generated', 'Generated'),
        ('approved', 'Approved'),
        ('published', 'Published'),
    ]
    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('ai', 'AI'),
    ]

    quiz = models.ForeignKey(LessonQuiz, on_delete=models.CASCADE, related_name='translations')
    language_code = models.CharField(max_length=10)
    title = models.CharField(max_length=200, blank=True, default='')
    description = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    translation_source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('quiz', 'language_code')]
        ordering = ['language_code']

    def __str__(self):
        return f"Quiz translation [{self.language_code}] for {self.quiz.lesson.title}"


class LessonQuizQuestionTranslation(models.Model):
    """Localized quiz question text and options. correct_option stays on the base question."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('generated', 'Generated'),
        ('approved', 'Approved'),
        ('published', 'Published'),
    ]
    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('ai', 'AI'),
    ]

    question = models.ForeignKey(LessonQuizQuestion, on_delete=models.CASCADE, related_name='translations')
    language_code = models.CharField(max_length=10)
    text = models.TextField(blank=True, default='')
    option_a = models.CharField(max_length=300, blank=True, default='')
    option_b = models.CharField(max_length=300, blank=True, default='')
    option_c = models.CharField(max_length=300, blank=True, default='')
    option_d = models.CharField(max_length=300, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    translation_source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('question', 'language_code')]
        ordering = ['language_code']

    def __str__(self):
        return f"Question translation [{self.language_code}] Q{self.question.order}"


class LessonQuizAttempt(models.Model):
    """Track a student's attempts for a lesson quiz."""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='lesson_quiz_attempts', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lesson_quiz_attempts')
    quiz = models.ForeignKey(LessonQuiz, on_delete=models.CASCADE, related_name='attempts')
    score = models.FloatField(null=True, blank=True, help_text="Score percentage (0–100)")
    passed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-completed_at']

    def __str__(self):
        status = "Passed" if self.passed else "Failed"
        return f"{self.user.username} - {self.quiz.lesson.title} - {status}"

class UserProgress(models.Model):
    STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='user_progress_records', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='progress')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='user_progress')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_started')
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    progress_percentage = models.IntegerField(default=0, help_text="Overall lesson progress percentage")
    
    # Video Watch Progress Tracking
    video_watch_percentage = models.FloatField(default=0.0, help_text="Percentage of video watched (0-100)")
    last_watched_timestamp = models.FloatField(default=0.0, help_text="Last timestamp in seconds where video was watched")
    video_completion_threshold = models.FloatField(default=90.0, help_text="Required watch percentage to complete (default 90%)")
    
    last_accessed = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ['tenant', 'user', 'lesson']
        ordering = ['-last_accessed']
    
    def __str__(self):
        return f"{self.user.username} - {self.lesson.title}"

    def save(self, *args, **kwargs):
        # Defensive tenancy guard: some legacy code paths may miss tenant.
        if self.tenant_id is None:
            self.tenant = (
                getattr(self.lesson, 'tenant', None)
                or getattr(getattr(self.lesson, 'course', None), 'tenant', None)
                or Tenant.objects.get_or_create(
                    slug='default',
                    defaults={
                        'name': 'Default Tenant',
                        'primary_color': '#3B82F6',
                        'is_active': True,
                    },
                )[0]
            )
        super().save(*args, **kwargs)
    
    def update_status(self):
        """Automatically update status based on progress"""
        if self.video_watch_percentage >= self.video_completion_threshold:
            self.status = 'completed'
            self.completed = True
            if not self.completed_at:
                self.completed_at = timezone.now()
        elif self.video_watch_percentage > 0:
            self.status = 'in_progress'
            if not self.started_at:
                self.started_at = timezone.now()
        else:
            self.status = 'not_started'
        self.save()


class CourseEnrollment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='course_enrollments', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    enrolled_at = models.DateTimeField(auto_now_add=True)
    payment_type = models.CharField(max_length=20, choices=[
        ('full', 'Full Payment'),
        ('installment', 'Installment'),
    ], default='full')
    
    class Meta:
        unique_together = ['tenant', 'user', 'course']
    
    def __str__(self):
        return f"{self.user.username} - {self.course.name}"
    
    def days_until_exam(self):
        if self.payment_type == 'full':
            return 0
        days_elapsed = (timezone.now() - self.enrolled_at).days
        return max(0, self.course.exam_unlock_days - days_elapsed)
    
    def is_exam_available(self):
        """Check if exam is available based on payment type and course completion"""
        if self.payment_type == 'full':
            # Check if all lessons are completed
            total_lessons = self.course.lessons.count()
            completed_lessons = UserProgress.objects.filter(
                user=self.user,
                lesson__course=self.course,
                completed=True
            ).count()
            return completed_lessons >= total_lessons
        else:
            return self.days_until_exam() == 0
    
    def get_certification_status(self):
        """Get current certification status"""
        try:
            cert = Certification.objects.get(user=self.user, course=self.course)
            return cert.status
        except Certification.DoesNotExist:
            # Check if eligible
            if self.is_exam_available():
                return 'eligible'
            return 'not_eligible'


class FavoriteCourse(models.Model):
    """Track user's favorite courses"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='favorite_courses', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorite_courses')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['tenant', 'user', 'course']
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} favorited {self.course.name}"


class Exam(models.Model):
    """Final exam for a course"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='exams', null=True, blank=True)
    course = models.OneToOneField(Course, on_delete=models.CASCADE, related_name='exam')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    passing_score = models.IntegerField(default=70, help_text="Minimum score percentage to pass")
    max_attempts = models.IntegerField(default=3, help_text="Maximum number of attempts allowed (0 = unlimited)")
    time_limit_minutes = models.IntegerField(null=True, blank=True, help_text="Time limit in minutes (null = no limit)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.course.name} - {self.title}"


class ExamQuestion(models.Model):
    """Multiple-choice question for a course final exam."""
    OPTION_CHOICES = [
        ('A', 'Option A'),
        ('B', 'Option B'),
        ('C', 'Option C'),
        ('D', 'Option D'),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='exam_questions', null=True, blank=True)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField()
    option_a = models.CharField(max_length=300)
    option_b = models.CharField(max_length=300)
    option_c = models.CharField(max_length=300, blank=True)
    option_d = models.CharField(max_length=300, blank=True)
    correct_option = models.CharField(max_length=1, choices=OPTION_CHOICES)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"Q{self.order} for {self.exam.course.name}"


class ExamAttempt(models.Model):
    """Track individual exam attempts"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='exam_attempts', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exam_attempts')
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='attempts')
    score = models.FloatField(null=True, blank=True, help_text="Score percentage (0-100)")
    passed = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_taken_seconds = models.IntegerField(null=True, blank=True)
    answers = models.JSONField(default=dict, blank=True, help_text="Student's answers")
    is_final = models.BooleanField(default=False, help_text="Whether this is the final/current attempt")
    
    class Meta:
        ordering = ['-started_at']
    
    def __str__(self):
        status = "Passed" if self.passed else "Failed"
        return f"{self.user.username} - {self.exam.course.name} - Attempt {self.attempt_number()} - {status}"
    
    def attempt_number(self):
        """Get the attempt number for this user and exam"""
        return ExamAttempt.objects.filter(
            user=self.user,
            exam=self.exam,
            started_at__lte=self.started_at
        ).count()


class Certification(models.Model):
    """Track certification status and Accredible integration"""
    STATUS_CHOICES = [
        ('not_eligible', 'Not Eligible'),
        ('eligible', 'Eligible'),
        ('passed', 'Passed - Certified'),
        ('failed', 'Failed - Retry Allowed'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='certifications', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='certifications')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='certifications')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_eligible')
    
    # Accredible Integration
    accredible_certificate_id = models.CharField(max_length=200, blank=True, help_text="Accredible certificate ID")
    accredible_certificate_url = models.URLField(blank=True, help_text="Link to Accredible certificate")
    issued_at = models.DateTimeField(null=True, blank=True)
    
    # Related exam attempt that resulted in certification
    passing_exam_attempt = models.ForeignKey(
        'ExamAttempt',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='certifications'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['tenant', 'user', 'course']
        ordering = ['-issued_at', '-created_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.course.name} - {self.get_status_display()}"

# ========== ACCESS CONTROL SYSTEM ==========

class Cohort(models.Model):
    """Groups of students (e.g., 'Black Friday 2025 Buyers', 'VIP Mastermind')"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='cohorts', null=True, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'name'], name='uniq_cohort_tenant_name')
        ]
    
    def __str__(self):
        return self.name
    
    def get_member_count(self):
        return self.members.count()


class Bundle(models.Model):
    """Product/Bundle that grants access to multiple courses"""
    BUNDLE_TYPES = [
        ('fixed', 'Fixed Bundle (curated set)'),
        ('pick_your_own', 'Pick Your Own (choose N courses)'),
        ('tiered', 'Tiered (Bronze/Silver/Gold)'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='bundles', null=True, blank=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True)
    bundle_type = models.CharField(max_length=20, choices=BUNDLE_TYPES, default='fixed')
    courses = models.ManyToManyField(Course, related_name='bundles', blank=True)
    max_course_selections = models.IntegerField(null=True, blank=True, help_text="For pick-your-own bundles")
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'slug'], name='uniq_bundle_tenant_slug'),
            models.UniqueConstraint(fields=['tenant', 'name'], name='uniq_bundle_tenant_name'),
        ]
    
    def __str__(self):
        return self.name


class BundlePurchase(models.Model):
    """Track bundle purchases"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='bundle_purchases', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bundle_purchases')
    bundle = models.ForeignKey(Bundle, on_delete=models.CASCADE, related_name='purchases')
    purchase_id = models.CharField(max_length=200, blank=True, help_text="External purchase/order ID")
    purchase_date = models.DateTimeField(auto_now_add=True)
    selected_courses = models.ManyToManyField(Course, blank=True, help_text="For pick-your-own bundles")
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-purchase_date']
    
    def __str__(self):
        return f"{self.user.username} - {self.bundle.name}"


class Coupon(models.Model):
    """Promotional coupon with a shareable link and optional Iceberg-hosted QR code."""
    DISCOUNT_NONE = 'none'
    DISCOUNT_PERCENT = 'percent'
    DISCOUNT_FIXED = 'fixed'
    DISCOUNT_TYPES = [
        (DISCOUNT_NONE, 'No discount (tracking only)'),
        (DISCOUNT_PERCENT, 'Percent off'),
        (DISCOUNT_FIXED, 'Fixed amount off'),
    ]

    TARGET_SIGNUP = 'signup'
    TARGET_COURSE = 'course'
    TARGET_BUNDLE = 'bundle'
    TARGET_CUSTOM = 'custom'
    TARGET_SITE = 'site'
    TARGET_TYPES = [
        (TARGET_SIGNUP, 'Tenant signup page'),
        (TARGET_COURSE, 'Course'),
        (TARGET_BUNDLE, 'Bundle'),
        (TARGET_CUSTOM, 'Custom URL'),
        (TARGET_SITE, 'Site home'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='coupons', null=True, blank=True)
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, help_text='Public coupon code used in the shareable link')
    description = models.TextField(blank=True)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPES, default=DISCOUNT_PERCENT)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    target_type = models.CharField(max_length=20, choices=TARGET_TYPES, default=TARGET_SIGNUP)
    course = models.ForeignKey(
        Course, on_delete=models.SET_NULL, null=True, blank=True, related_name='coupons',
    )
    bundle = models.ForeignKey(
        Bundle, on_delete=models.SET_NULL, null=True, blank=True, related_name='coupons',
    )
    custom_url = models.URLField(blank=True, max_length=500)
    qr_code_url = models.URLField(
        blank=True, max_length=500,
        help_text='Iceberg CDN URL for the coupon QR image',
    )
    is_active = models.BooleanField(default=True)
    max_uses = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Leave blank for unlimited uses',
    )
    uses_count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'code'], name='uniq_coupon_tenant_code'),
        ]

    def __str__(self):
        return f'{self.code} ({self.name})'

    def is_currently_valid(self):
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        if self.max_uses is not None and self.uses_count >= self.max_uses:
            return False
        return True

    def is_tracking_only(self):
        return self.discount_type == self.DISCOUNT_NONE

    def apply_discount(self, amount):
        """Return discounted Decimal amount (never below zero)."""
        from decimal import Decimal
        amount = Decimal(str(amount or 0))
        if amount <= 0:
            return Decimal('0.00')
        if self.discount_type == self.DISCOUNT_NONE:
            return amount.quantize(Decimal('0.01'))
        if self.discount_type == self.DISCOUNT_PERCENT:
            discounted = amount * (Decimal('1') - (Decimal(str(self.discount_value)) / Decimal('100')))
        else:
            discounted = amount - Decimal(str(self.discount_value))
        if discounted < 0:
            discounted = Decimal('0.00')
        return discounted.quantize(Decimal('0.01'))


class CourseAccess(models.Model):
    """Explicit access record - 'Access is a thing, not a side effect'"""
    ACCESS_TYPES = [
        ('purchase', 'Purchase'),
        ('manual', 'Manual (Admin-granted)'),
        ('cohort', 'Cohort/Group'),
        ('subscription', 'Subscription/Membership'),
        ('bundle', 'Bundle Purchase'),
    ]
    
    STATUS_CHOICES = [
        ('unlocked', 'Unlocked (Active)'),
        ('locked', 'Locked'),
        ('revoked', 'Revoked'),
        ('expired', 'Expired'),
        ('pending', 'Pending'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='course_accesses', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='course_accesses')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='accesses')
    access_type = models.CharField(max_length=20, choices=ACCESS_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unlocked')
    
    # Source tracking
    bundle_purchase = models.ForeignKey(
        BundlePurchase, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='granted_accesses'
    )
    cohort = models.ForeignKey(
        Cohort,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='granted_accesses'
    )
    purchase_id = models.CharField(max_length=200, null=True, blank=True, help_text="External purchase ID")
    
    # Dates
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='granted_accesses',
        help_text="Admin who granted access (for manual access)"
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='revoked_accesses',
        help_text="Admin who revoked access"
    )
    revocation_reason = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True, help_text="Support notes, audit trail")
    
    class Meta:
        ordering = ['-granted_at']
        indexes = [
            models.Index(fields=['user', 'course', 'status']),
            models.Index(fields=['status', 'expires_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.course.name} - {self.get_access_type_display()}"
    
    def is_active(self):
        """Check if access is currently active"""
        if self.status != 'unlocked':
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True
    
    def get_source_display(self):
        """Get human-readable source of access"""
        if self.bundle_purchase:
            return f"Bundle: {self.bundle_purchase.bundle.name}"
        elif self.cohort:
            return f"Cohort: {self.cohort.name}"
        elif self.access_type == 'manual':
            return f"Manual (by {self.granted_by.username if self.granted_by else 'Admin'})"
        elif self.purchase_id:
            return f"Purchase: {self.purchase_id}"
        return self.get_access_type_display()


class CohortMember(models.Model):
    """Link users to cohorts"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='cohort_memberships', null=True, blank=True)
    cohort = models.ForeignKey(Cohort, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cohorts')
    joined_at = models.DateTimeField(auto_now_add=True)
    remove_access_on_leave = models.BooleanField(
        default=True,
        help_text="If True, removing from cohort revokes access. If False, access persists."
    )
    
    class Meta:
        unique_together = ['cohort', 'user']
        ordering = ['-joined_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.cohort.name}"


class LearningPath(models.Model):
    """Curated learning journeys (e.g., '7-Figure Launch Path')"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='learning_paths', null=True, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    courses = models.ManyToManyField(Course, through='LearningPathCourse', related_name='learning_paths')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class LearningPathCourse(models.Model):
    """Ordered courses in a learning path"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='learning_path_courses', null=True, blank=True)
    learning_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    order = models.IntegerField(default=0)
    is_required = models.BooleanField(default=True, help_text="Must complete to unlock next")
    
    class Meta:
        ordering = ['order']
        unique_together = ['learning_path', 'course']
    
    def __str__(self):
        return f"{self.learning_path.name} - {self.course.name} (#{self.order})"


class TenantMembership(models.Model):
    """Links Django users to tenants with a role."""
    ROLE_CHOICES = [
        ('tenant_admin', 'Tenant Admin'),
        ('student', 'Student'),
    ]

    THEME_CHOICES = [
        ('', 'Use tenant default'),
        ('dark', 'Dark'),
        ('light', 'Light'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tenant_memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='student')
    is_active = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=False)
    theme_preference = models.CharField(max_length=10, choices=THEME_CHOICES, blank=True, default='')
    signup_coupon = models.ForeignKey(
        'Coupon',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='signup_memberships',
        help_text='Coupon used when this student created their account',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['tenant', 'user']
        ordering = ['tenant__name', 'user__username']
        indexes = [
            models.Index(fields=['tenant', 'role', 'is_active']),
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        return f"{self.user.username} @ {self.tenant.slug} ({self.role})"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    preferred_language = models.CharField(max_length=10, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile for {self.user.username}"


class StudentIPLog(models.Model):
    """Tenant-scoped student IP activity rollup."""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='student_ip_logs')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='student_ip_logs')
    ip_address = models.CharField(max_length=64)
    country = models.CharField(max_length=120, blank=True, default='')
    region = models.CharField(max_length=120, blank=True, default='')
    city = models.CharField(max_length=120, blank=True, default='')
    is_private_ip = models.BooleanField(default=False)
    last_path = models.CharField(max_length=500, blank=True, default='')
    hit_count = models.PositiveIntegerField(default=1)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_seen']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'user', 'ip_address'], name='uniq_student_iplog_tenant_user_ip')
        ]
        indexes = [
            models.Index(fields=['tenant', 'last_seen']),
            models.Index(fields=['tenant', 'ip_address']),
            models.Index(fields=['tenant', 'is_private_ip']),
            models.Index(fields=['tenant', 'country']),
        ]

    def __str__(self):
        return f"{self.user.username} @ {self.tenant.slug} ({self.ip_address})"


class AIUsageLog(models.Model):
    """Per-call OpenAI usage log for tenant/course cost analytics."""
    PROVIDER_CHOICES = [
        ('openai', 'OpenAI'),
    ]

    FEATURE_CHOICES = [
        ('course_structure', 'Course Structure'),
        ('lesson_metadata', 'Lesson Metadata'),
        ('lesson_content', 'Lesson Content'),
        ('lesson_image', 'Lesson Image'),
        ('lesson_audio', 'Lesson Audio'),
        ('lesson_quiz', 'Lesson Quiz'),
        ('course_exam', 'Course Exam'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_usage_logs',
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_usage_logs',
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_usage_logs',
    )

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='openai')
    feature = models.CharField(max_length=40, choices=FEATURE_CHOICES)
    model_name = models.CharField(max_length=80, blank=True)
    request_id = models.CharField(max_length=120, blank=True)

    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)

    input_rate_per_million = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    output_rate_per_million = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'created_at']),
            models.Index(fields=['course', 'created_at']),
            models.Index(fields=['feature', 'created_at']),
        ]

    def __str__(self):
        return f"{self.provider}:{self.feature}:{self.model_name} ({self.total_tokens} tokens)"


class StripeEventLog(models.Model):
    """Idempotency ledger for Stripe webhook events."""
    event_id = models.CharField(max_length=120, unique=True)
    event_type = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.event_type or 'event'}:{self.event_id}"


# ========== PRICING & NOTIFICATIONS ==========

class PricingTier(models.Model):
    """Editable pricing tier, manually synced to Stripe."""
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    setup_fee_cents = models.PositiveIntegerField()
    monthly_cents = models.PositiveIntegerField()
    yearly_cents = models.PositiveIntegerField()
    stripe_product_id = models.CharField(max_length=100, blank=True)
    stripe_price_setup_id = models.CharField(max_length=100, blank=True)
    stripe_price_monthly_id = models.CharField(max_length=100, blank=True)
    stripe_price_yearly_id = models.CharField(max_length=100, blank=True)
    stripe_synced_at = models.DateTimeField(null=True, blank=True)
    charge_setup_fee = models.BooleanField(
        default=True,
        help_text="If False, setup fee is skipped at checkout for this tier.",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

    @property
    def needs_sync(self):
        return self.stripe_synced_at is None or self.updated_at > self.stripe_synced_at


class TenantNotification(models.Model):
    """Superadmin-created notification: modal + email."""
    CTA_TYPES = [
        ('none', 'No CTA'),
        ('upgrade', 'Upgrade to tier'),
        ('setup_fee', 'Pay setup fee'),
        ('url', 'Custom URL'),
    ]

    title = models.CharField(max_length=200)
    body = models.TextField(help_text="Supports HTML")
    cta_type = models.CharField(max_length=20, choices=CTA_TYPES, default='none')
    cta_label = models.CharField(max_length=100, blank=True)
    cta_tier = models.ForeignKey(
        PricingTier, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='notifications',
    )
    cta_billing_interval = models.CharField(
        max_length=10, blank=True,
        choices=[('monthly', 'Monthly'), ('yearly', 'Yearly')],
    )
    cta_custom_url = models.URLField(blank=True)
    send_email = models.BooleanField(default=True)
    show_modal = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class TenantNotificationDelivery(models.Model):
    """Per-tenant tracking row."""
    notification = models.ForeignKey(
        TenantNotification, on_delete=models.CASCADE, related_name='deliveries',
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='notification_deliveries')
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_error = models.TextField(blank=True)
    seen_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('notification', 'tenant')]
        ordering = ['-notification__created_at']

    def __str__(self):
        return f"{self.notification.title} → {self.tenant.name}"


# ─── Community Forum ────────────────────────────────────────────────

class ForumCategory(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='forum_categories')
    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=80)
    description = models.CharField(max_length=200, blank=True, default='')
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('tenant', 'slug')]
        ordering = ['order', 'name']
        verbose_name_plural = 'forum categories'

    def __str__(self):
        return self.name


class ForumPost(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='forum_posts')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='forum_posts')
    category = models.ForeignKey(
        ForumCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='posts',
    )
    content = models.TextField()
    image = models.ImageField(upload_to='forum_images/', null=True, blank=True)
    is_pinned = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_pinned', '-created_at']
        indexes = [
            models.Index(fields=['tenant', '-created_at']),
            models.Index(fields=['tenant', 'author']),
            models.Index(fields=['tenant', 'category']),
        ]

    def __str__(self):
        return f"Post by {self.author.username} ({self.tenant.slug})"


class ForumComment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='forum_comments')
    post = models.ForeignKey(ForumPost, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='forum_comments')
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies',
    )
    content = models.TextField()
    is_edited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['post', 'created_at']),
        ]

    def __str__(self):
        return f"Comment by {self.author.username} on post {self.post_id}"


class ForumReaction(models.Model):
    REACTION_CHOICES = [
        ('like', 'Like'),
        ('celebrate', 'Celebrate'),
        ('support', 'Support'),
        ('insightful', 'Insightful'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='forum_reactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='forum_reactions')
    post = models.ForeignKey(
        ForumPost, on_delete=models.CASCADE, null=True, blank=True, related_name='reactions',
    )
    comment = models.ForeignKey(
        ForumComment, on_delete=models.CASCADE, null=True, blank=True, related_name='reactions',
    )
    reaction_type = models.CharField(max_length=20, choices=REACTION_CHOICES, default='like')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['post', 'reaction_type']),
            models.Index(fields=['comment', 'reaction_type']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'user', 'post', 'reaction_type'],
                condition=models.Q(post__isnull=False),
                name='uniq_forum_reaction_post',
            ),
            models.UniqueConstraint(
                fields=['tenant', 'user', 'comment', 'reaction_type'],
                condition=models.Q(comment__isnull=False),
                name='uniq_forum_reaction_comment',
            ),
        ]

    def __str__(self):
        target = f"post {self.post_id}" if self.post_id else f"comment {self.comment_id}"
        return f"{self.user.username} {self.reaction_type} on {target}"


class Event(models.Model):
    """
    A standalone live event (Zoom/Google Meet, etc.) — NOT a course type.
    Mirrors Course's tenant scoping and per-tenant unique slug. A single
    session is described by event_date + start_time + timezone + duration.
    The join link is only exposed to registered users (see has_event_access).
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='events', null=True, blank=True)
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    short_description = models.CharField(max_length=1000, blank=True)
    description = models.TextField(blank=True)
    thumbnail = models.ImageField(upload_to='event_thumbnails/', null=True, blank=True)
    host_name = models.CharField(max_length=100, blank=True, help_text="Person/team hosting the event")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    display_order = models.PositiveIntegerField(default=0, help_text="Lower numbers appear first in event listings.")

    # Schedule (single session)
    event_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default='UTC', help_text="IANA timezone name, e.g. America/New_York")
    duration_minutes = models.PositiveIntegerField(default=60, help_text="Length of the event in minutes")

    # Access
    join_link = models.URLField(max_length=500, blank=True, help_text="Zoom/Google Meet link — only shown to registered users")

    # Provenance. GHL-synced events carry the source ids so re-syncs upsert
    # (never duplicate) and manually-created events are never clobbered.
    SOURCE_CHOICES = [('manual', 'Manual'), ('ghl', 'GHL')]
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    ghl_event_id = models.CharField(max_length=128, blank=True, default='')
    ghl_calendar_id = models.CharField(max_length=128, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['event_date', 'start_time']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'slug'], name='uniq_event_tenant_slug'),
            models.UniqueConstraint(
                fields=['tenant', 'ghl_event_id'],
                condition=models.Q(source='ghl'),
                name='uniq_event_tenant_ghl_event',
            ),
        ]

    def __str__(self):
        return self.title

    def get_start_datetime(self):
        """Combine event_date + start_time into a timezone-aware datetime, or None."""
        if not self.event_date or not self.start_time:
            return None
        import datetime
        naive = datetime.datetime.combine(self.event_date, self.start_time)
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(self.timezone or 'UTC')
        except Exception:
            from django.utils.timezone import get_default_timezone
            tz = get_default_timezone()
        return naive.replace(tzinfo=tz)

    def get_end_datetime(self):
        start = self.get_start_datetime()
        if start is None:
            return None
        import datetime
        return start + datetime.timedelta(minutes=self.duration_minutes or 0)

    def is_past(self):
        end = self.get_end_datetime() or self.get_start_datetime()
        if end is None:
            return False
        return end < timezone.now()

    def is_upcoming(self):
        start = self.get_start_datetime()
        if start is None:
            return False
        return not self.is_past()

    def registration_count(self):
        return self.registrations.count()


class EventRegistration(models.Model):
    """A user's free registration for an Event. Mirrors CourseEnrollment."""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='event_registrations', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_registrations')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='registrations')
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['tenant', 'user', 'event']
        ordering = ['-registered_at']

    def __str__(self):
        return f"{self.user.username} - {self.event.title}"


class MembershipPlan(models.Model):
    """
    Optional per-tenant recurring student membership. When enabled, an active
    StudentSubscription unlocks the whole catalog (all active, non-private
    courses) alongside existing per-course and bundle purchases.
    """
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='membership_plan')
    is_enabled = models.BooleanField(default=False)
    name = models.CharField(max_length=200, default='All-Access Membership')
    description = models.TextField(blank=True, help_text='Student-facing pitch for the membership')
    monthly_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Monthly price in USD. Leave blank to disable monthly billing.',
    )
    yearly_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Yearly price in USD. Leave blank to disable yearly billing.',
    )
    past_due_grace_days = models.PositiveIntegerField(
        default=0,
        help_text=(
            'Days a member keeps access after a failed renewal (status past_due) '
            'while Stripe retries payment. 0 = revoke access immediately. A few '
            'days avoids locking out members over a transient card decline.'
        ),
    )
    tiers_cumulative = models.BooleanField(
        default=True,
        help_text=(
            'When multiple membership tiers exist, a higher tier also unlocks '
            'every lower tier\u2019s courses (Pro \u2287 Starter). Turn off to make '
            'each tier an independent, standalone course set.'
        ),
    )
    member_pricing_requires_annual = models.BooleanField(
        default=False,
        help_text=(
            'If on, only annual and complimentary members get member pricing on '
            'courses; monthly members pay the standard price. Prevents "pay one '
            'month, grab the discount, cancel." Off = any active member gets it.'
        ),
    )
    comp_grant_reset = models.BooleanField(
        default=False,
        help_text=(
            'How a new complimentary grant combines with remaining time. On = '
            'reset to N months from the latest purchase. Off = extend/stack N '
            'months onto whatever time is left.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Membership plan for {self.tenant.slug}"

    def is_purchasable(self):
        """Enabled and has at least one price configured."""
        return bool(self.is_enabled and (self.monthly_price or self.yearly_price))


class MembershipTier(models.Model):
    """
    One purchasable membership level for a tenant (e.g. Starter / Pro / All-Access).

    A tenant may define several. Each unlocks a set of courses (its own ``courses``
    plus, when ``MembershipPlan.tiers_cumulative`` is on, every lower-rank tier's
    courses), or the whole catalog when ``includes_all`` is set. A student's
    ``StudentSubscription`` points at exactly one tier when ``access_mode='tiered'``.

    Distinct from ``PricingTier`` (the platform's SaaS pricing for tenants).
    """
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='membership_tiers')
    code = models.SlugField(max_length=60, help_text='Short identifier, unique per tenant (e.g. "starter").')
    name = models.CharField(max_length=200, default='Membership')
    description = models.TextField(blank=True, help_text='Student-facing pitch for this tier')
    rank = models.PositiveIntegerField(
        default=0, help_text='Ordering weight; higher = more inclusive (Pro > Starter).',
    )
    monthly_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Monthly price in USD. Blank disables monthly billing for this tier.',
    )
    yearly_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Yearly price in USD. Blank disables yearly billing for this tier.',
    )
    includes_all = models.BooleanField(
        default=False, help_text='All-access tier: unlocks the entire catalog.',
    )
    is_purchasable = models.BooleanField(
        default=True,
        help_text=(
            'Whether NEW checkouts can select this tier. Turning it off stops new '
            'signups but never revokes access for current subscribers.'
        ),
    )
    is_archived = models.BooleanField(
        default=False,
        help_text='Soft-deleted: hidden from admin/checkout but retained for reporting and existing subscribers.',
    )
    # Persistent Stripe objects so checkout references a stored price, upgrades
    # are possible, and price_id -> tier repair works if state drifts.
    stripe_product_id = models.CharField(max_length=120, blank=True, default='')
    stripe_monthly_price_id = models.CharField(max_length=120, blank=True, default='')
    stripe_yearly_price_id = models.CharField(max_length=120, blank=True, default='')
    courses = models.ManyToManyField(
        Course, blank=True, related_name='membership_tiers',
        help_text='Courses this tier unlocks (before cumulative lower-tier inclusion).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('tenant', 'code'), ('tenant', 'rank')]
        ordering = ['rank', 'id']
        indexes = [
            models.Index(fields=['tenant', 'is_archived', 'is_purchasable']),
        ]

    def __str__(self):
        return f"{self.name} ({self.tenant.slug})"

    def clean(self):
        # Guard against cross-tenant course links accumulating invisibly.
        if self.pk:
            bad = self.courses.exclude(tenant=self.tenant).exists()
            if bad:
                from django.core.exceptions import ValidationError
                raise ValidationError('All courses in a tier must belong to the same tenant.')

    def price_for(self, interval):
        return self.monthly_price if interval == 'month' else self.yearly_price

    def stripe_price_id_for(self, interval):
        return self.stripe_monthly_price_id if interval == 'month' else self.stripe_yearly_price_id

    def is_available(self):
        """Selectable for a new checkout: purchasable, not archived, has a price."""
        return bool(
            self.is_purchasable and not self.is_archived
            and (self.monthly_price or self.yearly_price)
        )


class StudentSubscription(models.Model):
    """A student's recurring membership to a tenant's whole catalog."""
    INTERVAL_CHOICES = [
        ('month', 'Monthly'),
        ('year', 'Yearly'),
    ]
    STATUS_CHOICES = [
        ('incomplete', 'Incomplete'),
        ('active', 'Active'),
        ('past_due', 'Past Due'),
        ('canceled', 'Canceled'),
        ('expired', 'Expired'),
    ]
    ACCESS_MODE_CHOICES = [
        ('all_access', 'All-access (whole catalog)'),
        ('tiered', 'Tiered (specific membership tier)'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='student_subscriptions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='student_subscriptions')
    stripe_subscription_id = models.CharField(max_length=120, blank=True, default='')
    stripe_customer_id = models.CharField(max_length=120, blank=True, default='')
    interval = models.CharField(max_length=10, choices=INTERVAL_CHOICES, default='month')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='incomplete')
    access_mode = models.CharField(
        max_length=20, choices=ACCESS_MODE_CHOICES, default='all_access',
        help_text='all_access = whole catalog (legacy/comp); tiered = a specific MembershipTier.',
    )
    tier = models.ForeignKey(
        'MembershipTier', null=True, blank=True, on_delete=models.PROTECT,
        related_name='subscriptions',
        help_text='The membership tier held (only when access_mode=tiered).',
    )
    is_complimentary = models.BooleanField(
        default=False, help_text='Admin-granted free membership (no Stripe subscription).',
    )
    current_period_end = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['tenant', 'user']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'user', 'status']),
            models.Index(fields=['stripe_subscription_id']),
            models.Index(fields=['stripe_customer_id']),
        ]
        constraints = [
            models.CheckConstraint(
                name='studentsub_tier_matches_access_mode',
                check=(
                    models.Q(access_mode='tiered', tier__isnull=False)
                    | models.Q(access_mode='all_access', tier__isnull=True)
                ),
            ),
        ]

    def __str__(self):
        return f"{self.user.username} @ {self.tenant.slug} membership ({self.status})"

    def is_active(self, past_due_grace_days=0):
        """
        Whether this membership currently grants access.

        Active: not past its period end. Past-due (Stripe dunning): still grants
        access for `past_due_grace_days` after the period end, so a transient
        card decline doesn't lock the member out mid-retry. Any other status
        (incomplete/canceled/expired) never grants access.
        """
        now = timezone.now()
        if self.status == 'active':
            if self.current_period_end and now > self.current_period_end:
                return False
            return True
        if self.status == 'past_due' and past_due_grace_days > 0:
            if self.current_period_end is None:
                return True
            import datetime
            return now <= self.current_period_end + datetime.timedelta(days=past_due_grace_days)
        return False


class PendingRegistration(models.Model):
    """
    A signup that chose a membership and is being held until Stripe payment
    succeeds. The account is only created once payment completes (via the
    checkout success redirect or the webhook), so abandoned checkouts never
    leave an unpaid ghost account. The password is stored already-hashed.
    """
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='pending_registrations')
    username = models.CharField(max_length=150)
    email = models.EmailField(blank=True, default='')
    password = models.CharField(max_length=256, help_text='Already hashed (make_password).')
    interval = models.CharField(max_length=10, default='month')
    tier = models.ForeignKey(
        'MembershipTier', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='pending_registrations',
    )
    stripe_checkout_session_id = models.CharField(max_length=200, blank=True, default='', db_index=True)
    consumed = models.BooleanField(default=False, help_text='Account has been created from this record.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['stripe_checkout_session_id']),
            models.Index(fields=['consumed', 'created_at']),
        ]

    def __str__(self):
        state = 'consumed' if self.consumed else 'pending'
        return f"PendingRegistration({self.username} @ {self.tenant.slug}, {state})"


# ─── GHL (GoHighLevel) integration models ───
# Defined in a sibling module to keep this file focused; imported here so
# makemigrations/Django register them under the myApp app label.
from .models_ghl import GHLConnection, GHLLink  # noqa: E402,F401

