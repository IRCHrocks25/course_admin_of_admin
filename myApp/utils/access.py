"""
Access Control Utilities
Core concept: "Access is a thing, not a side effect"
"""
from django.utils import timezone
from django.db.models import Q
from ..models import CourseAccess, Course, CohortMember, BundlePurchase


def has_course_access(user, course):
    """
    Check if user has active access to a course.
    Returns (has_access: bool, access_record: CourseAccess or None, reason: str)
    """
    if not user.is_authenticated:
        return False, None, "Not authenticated"
    
    # Get all active access records for this user and course
    active_accesses = CourseAccess.objects.filter(
        user=user,
        course=course,
        status='unlocked'
    ).exclude(
        # Exclude expired accesses
        Q(expires_at__isnull=False) & Q(expires_at__lt=timezone.now())
    )
    
    if active_accesses.exists():
        access = active_accesses.first()
        return True, access, f"Access granted via {access.get_source_display()}"
    
    # Check if access exists but is expired/revoked
    any_access = CourseAccess.objects.filter(user=user, course=course).first()
    if any_access:
        if any_access.status == 'expired':
            return False, any_access, "Access has expired"
        elif any_access.status == 'revoked':
            return False, any_access, f"Access revoked: {any_access.revocation_reason or 'No reason provided'}"
        elif any_access.expires_at and timezone.now() > any_access.expires_at:
            # Mark as expired
            any_access.status = 'expired'
            any_access.save()
            return False, any_access, "Access has expired"
    
    return False, None, "No access found"


def batch_has_course_access(user, course_ids):
    """
    Batch check course access for multiple courses. Returns dict: course_id -> (has_access, access_record, reason)
    Use this to avoid N+1 when checking access for many courses.
    """
    if not user.is_authenticated or not course_ids:
        return {cid: (False, None, "Not authenticated") for cid in course_ids}
    
    now = timezone.now()
    accesses = CourseAccess.objects.filter(
        user=user,
        course_id__in=course_ids,
    ).select_related('course')
    
    result = {cid: (False, None, "No access found") for cid in course_ids}
    for acc in accesses:
        if acc.status == 'expired':
            result[acc.course_id] = (False, acc, "Access has expired")
        elif acc.status == 'revoked':
            result[acc.course_id] = (False, acc, f"Access revoked: {acc.revocation_reason or 'No reason'}")
        elif acc.expires_at and now > acc.expires_at:
            acc.status = 'expired'
            acc.save()
            result[acc.course_id] = (False, acc, "Access has expired")
        elif acc.status == 'unlocked' and (not acc.expires_at or acc.expires_at > now):
            result[acc.course_id] = (True, acc, f"Access granted via {acc.get_source_display()}")
    
    return result


def grant_course_access(user, course, access_type, granted_by=None, bundle_purchase=None, 
                       cohort=None, purchase_id=None, expires_at=None, notes=""):
    """
    Grant access to a course.
    Returns the created CourseAccess object.
    """
    access = CourseAccess.objects.create(
        user=user,
        course=course,
        access_type=access_type,
        status='unlocked',
        granted_by=granted_by,
        bundle_purchase=bundle_purchase,
        cohort=cohort,
        purchase_id=purchase_id,
        expires_at=expires_at,
        notes=notes
    )
    return access


def revoke_course_access(user, course, revoked_by, reason="", notes=""):
    """
    Revoke access to a course.
    Returns the updated CourseAccess object or None if no access found.
    """
    access = CourseAccess.objects.filter(
        user=user,
        course=course,
        status='unlocked'
    ).first()
    
    if access:
        access.status = 'revoked'
        access.revoked_at = timezone.now()
        access.revoked_by = revoked_by
        access.revocation_reason = reason
        if notes:
            access.notes = f"{access.notes}\n{notes}" if access.notes else notes
        access.save()
        return access
    return None


def get_user_accessible_courses(user):
    """
    Get all courses the user has active access to.
    Returns QuerySet of Course objects.
    """
    if not user.is_authenticated:
        return Course.objects.none()
    
    now = timezone.now()
    access_ids = CourseAccess.objects.filter(
        user=user,
        status='unlocked'
    ).exclude(
        Q(expires_at__isnull=False) & Q(expires_at__lt=now)
    ).values_list('course_id', flat=True)
    
    return Course.objects.filter(id__in=access_ids)


def get_courses_by_visibility(user):
    """
    Get courses organized by visibility rules.
    Returns dict with keys: 'my_courses', 'available_to_unlock', 'not_available'
    """
    if not user.is_authenticated:
        # For non-authenticated users, only show public courses
        public_courses = Course.objects.filter(visibility='public', status='active')
        return {
            'my_courses': Course.objects.none(),
            'available_to_unlock': public_courses,
            'not_available': Course.objects.none(),
        }
    
    # Get courses user has access to
    my_courses = get_user_accessible_courses(user)
    
    # Get all visible courses
    visible_courses = Course.objects.filter(
        Q(visibility='public') | 
        Q(visibility='members_only') |
        Q(visibility='hidden')  # Hidden courses can still be accessed if user has access
    ).filter(status='active')
    
    # Available to unlock = visible courses user doesn't have access to yet
    available_to_unlock = visible_courses.exclude(id__in=my_courses.values_list('id', flat=True))
    
    # Not available = private courses or courses with unmet prerequisites
    not_available = Course.objects.filter(
        visibility='private',
        status='active'
    )
    
    return {
        'my_courses': my_courses,
        'available_to_unlock': available_to_unlock,
        'not_available': not_available,
    }


def check_course_prerequisites(user, course):
    """
    Check if user has met prerequisites for a course.
    Returns (met: bool, missing_prerequisites: list)
    """
    if not course.prerequisite_courses.exists():
        return True, []
    
    missing = []
    for prereq in course.prerequisite_courses.all():
        has_access, _, _ = has_course_access(user, prereq)
        if not has_access:
            missing.append(prereq)
            continue
        
        # Check if prerequisite is completed
        from ..models import UserProgress
        total_lessons = prereq.lessons.count()
        completed_lessons = UserProgress.objects.filter(
            user=user,
            lesson__course=prereq,
            completed=True
        ).count()
        
        if total_lessons > 0 and completed_lessons < total_lessons:
            missing.append(prereq)
    
    return len(missing) == 0, missing


def grant_bundle_access(user, bundle_purchase):
    """
    Grant access to all courses in a bundle purchase.
    """
    bundle = bundle_purchase.bundle
    courses_to_grant = []
    
    if bundle.bundle_type == 'fixed':
        courses_to_grant = bundle.courses.all()
    elif bundle.bundle_type == 'pick_your_own':
        courses_to_grant = bundle_purchase.selected_courses.all()
    elif bundle.bundle_type == 'tiered':
        courses_to_grant = bundle.courses.all()
    
    granted_accesses = []
    for course in courses_to_grant:
        # Check if access already exists
        existing = CourseAccess.objects.filter(
            user=user,
            course=course,
            bundle_purchase=bundle_purchase
        ).first()
        
        if not existing:
            access = grant_course_access(
                user=user,
                course=course,
                access_type='bundle',
                bundle_purchase=bundle_purchase,
                purchase_id=bundle_purchase.purchase_id,
                notes=f"Granted via bundle purchase: {bundle.name}"
            )
            granted_accesses.append(access)
    
    return granted_accesses


def grant_cohort_access(user, cohort):
    """
    Grant access to all courses associated with a cohort.
    Note: This assumes cohorts have associated courses (you may need to add this relationship).
    """
    # For now, we'll grant access when user joins cohort
    # You may want to add a many-to-many relationship between Cohort and Course
    # to define which courses a cohort grants access to
    from ..models import CohortMember
    member, created = CohortMember.objects.get_or_create(
        user=user,
        cohort=cohort
    )
    
    # TODO: Add cohort.courses relationship if needed
    # For now, return empty list
    return []

