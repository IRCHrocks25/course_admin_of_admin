# Access Control System - User Guide

## Overview

The Access Control System implements the core concept: **"Access is a thing, not a side effect"**. Every student's access to a course is explicitly tracked with full audit trails, source tracking, and expiration management.

---

## 🚀 Quick Access

### Django Admin Panel (Current Method)

**URL:** `/admin/` (e.g., `http://localhost:8000/admin/`)

**Login:** Use your admin/staff credentials

**Available Features:**
- ✅ Bundles (Products)
- ✅ Cohorts (Groups)
- ✅ Course Access Management
- ✅ Bundle Purchases
- ✅ Learning Paths

---

## 📋 Available Features

### 1. **Bundles (Products)**

**Location:** Django Admin → Bundles

**What it does:**
- Create product bundles that grant access to multiple courses
- Perfect for Black Friday promos, course packages, etc.
- Supports 3 bundle types:
  - **Fixed Bundle**: Curated set of courses
  - **Pick Your Own**: Student chooses N courses
  - **Tiered**: Bronze/Silver/Gold tiers

**How to Use:**
1. Go to `/admin/myApp/bundle/`
2. Click "Add Bundle"
3. Fill in:
   - Name (e.g., "Black Friday 2025 Bundle")
   - Slug (auto-generated from name)
   - Bundle Type
   - Select courses to include
   - Price (optional)
4. Save

**Granting Bundle Access:**
- When someone purchases a bundle, create a `BundlePurchase` record
- The system automatically grants access to all courses in the bundle
- Access is tracked with full audit trail

---

### 2. **Cohorts (Groups)**

**Location:** Django Admin → Cohorts

**What it does:**
- Group students together (e.g., "Black Friday 2025 Buyers", "VIP Mastermind")
- Automatically grant course access to all members
- Perfect for managing large groups of students

**How to Use:**
1. Go to `/admin/myApp/cohort/`
2. Click "Add Cohort"
3. Fill in:
   - Name (e.g., "Black Friday 2025 Buyers")
   - Description
   - Is Active
4. Save

**Adding Members:**
1. Go to `/admin/myApp/cohortmember/`
2. Click "Add Cohort Member"
3. Select:
   - Cohort
   - User
   - Remove Access on Leave (if True, removing from cohort revokes access)

**Note:** Currently, cohorts don't have a direct course relationship. You'll need to manually grant course access via CourseAccess records when adding members, or extend the system to add a many-to-many relationship between Cohort and Course.

---

### 3. **Course Access Management**

**Location:** Django Admin → Course Accesses

**What it does:**
- Explicitly track every student's access to every course
- Shows source of access (Bundle, Manual, Cohort, Purchase, Subscription)
- Full audit trail with dates, who granted/revoked, reasons

**Access Types:**
- **Purchase**: Direct course purchase
- **Manual**: Admin-granted (comps, VIPs, support fixes)
- **Cohort**: Granted via cohort membership
- **Subscription**: Subscription/membership access
- **Bundle**: Granted via bundle purchase

**How to Grant Access:**
1. Go to `/admin/myApp/courseaccess/`
2. Click "Add Course Access"
3. Fill in:
   - User
   - Course
   - Access Type
   - Status (usually "Unlocked")
   - Source (Bundle Purchase, Cohort, Purchase ID, or Granted By for manual)
   - Expires At (optional - for time-limited access)
   - Notes (for audit trail)
4. Save

**How to Revoke Access:**
1. Find the CourseAccess record
2. Edit it
3. Change Status to "Revoked"
4. Fill in:
   - Revoked By (select yourself)
   - Revocation Reason
   - Notes
5. Save

---

### 4. **Bundle Purchases**

**Location:** Django Admin → Bundle Purchases

**What it does:**
- Track when someone purchases a bundle
- Automatically grants access to all courses in the bundle
- Links to external purchase/order IDs

**How to Use:**
1. Go to `/admin/myApp/bundlepurchase/`
2. Click "Add Bundle Purchase"
3. Fill in:
   - User
   - Bundle
   - Purchase ID (external order ID)
   - Selected Courses (for pick-your-own bundles)
   - Notes
4. Save

**After Creating:**
- The system will automatically create CourseAccess records for all courses in the bundle
- Access is linked to the bundle purchase for full traceability

---

### 5. **Learning Paths**

**Location:** Django Admin → Learning Paths

**What it does:**
- Create curated learning journeys (e.g., "7-Figure Launch Path")
- Define course order and prerequisites
- Students complete one course to unlock the next

**How to Use:**
1. Go to `/admin/myApp/learningpath/`
2. Click "Add Learning Path"
3. Fill in Name and Description
4. Add courses via "Learning Path Courses":
   - Go to `/admin/myApp/learningpathcourse/`
   - Add courses in order
   - Set `is_required` to True if course must be completed to unlock next

---

## 🔧 Utility Functions (For Developers)

**Location:** `myApp/utils/access.py`

These functions can be used in your code or Django shell:

### Check Access
```python
from myApp.utils.access import has_course_access

has_access, access_record, reason = has_course_access(user, course)
if has_access:
    print(f"Access granted via: {access_record.get_source_display()}")
```

### Grant Access
```python
from myApp.utils.access import grant_course_access
from django.utils import timezone
from datetime import timedelta

# Grant lifetime access
access = grant_course_access(
    user=user,
    course=course,
    access_type='manual',
    granted_by=admin_user,
    notes="VIP comp access"
)

# Grant time-limited access (30 days)
expires_at = timezone.now() + timedelta(days=30)
access = grant_course_access(
    user=user,
    course=course,
    access_type='manual',
    granted_by=admin_user,
    expires_at=expires_at,
    notes="Trial access"
)
```

### Revoke Access
```python
from myApp.utils.access import revoke_course_access

revoke_course_access(
    user=user,
    course=course,
    revoked_by=admin_user,
    reason="Refund processed",
    notes="Customer requested refund"
)
```

### Grant Bundle Access
```python
from myApp.utils.access import grant_bundle_access

# After creating a BundlePurchase
granted_accesses = grant_bundle_access(user, bundle_purchase)
print(f"Granted access to {len(granted_accesses)} courses")
```

### Get User's Accessible Courses
```python
from myApp.utils.access import get_user_accessible_courses

accessible_courses = get_user_accessible_courses(user)
for course in accessible_courses:
    print(course.name)
```

### Check Prerequisites
```python
from myApp.utils.access import check_course_prerequisites

met, missing = check_course_prerequisites(user, course)
if not met:
    print(f"Missing prerequisites: {[c.name for c in missing]}")
```

---

## 📊 Course Availability Settings

**Location:** Django Admin → Courses → Edit Course

When creating/editing a course, you can now set:

### Visibility
- **Public**: Visible to anyone (even logged out)
- **Members Only**: Visible to logged-in users
- **Hidden**: Not in catalog, direct link only
- **Private**: Manual assignment only

### Enrollment Method
- **Open Enrollment**: Free/lead magnet style
- **Purchase Required**: Must purchase
- **Invite/Assigned Only**: Manual assignment
- **Cohort Only**: Only students in selected cohorts
- **Subscription Only**: Requires active subscription

### Access Duration
- **Lifetime Access**: Never expires
- **Fixed Duration**: X days from grant date
- **Access Until Date**: Expires on specific date
- **Drip Schedule**: Unlocks over time

### Prerequisites
- Select courses that must be completed first
- Students can't access until prerequisites are met

---

## 🎯 Common Workflows

### Workflow 1: Black Friday Bundle

1. **Create Bundle:**
   - Admin → Bundles → Add Bundle
   - Name: "Black Friday 2025 Bundle"
   - Type: Fixed Bundle
   - Select courses: Course A, B, C
   - Price: $997
   - Save

2. **When Customer Purchases:**
   - Admin → Bundle Purchases → Add Bundle Purchase
   - User: [select customer]
   - Bundle: "Black Friday 2025 Bundle"
   - Purchase ID: "BF2025-12345"
   - Save
   - ✅ Access automatically granted to all courses

### Workflow 2: Grant Manual Access (VIP/Comp)

1. **Grant Access:**
   - Admin → Course Accesses → Add Course Access
   - User: [select user]
   - Course: [select course]
   - Access Type: Manual
   - Granted By: [your admin user]
   - Notes: "VIP comp - influencer partnership"
   - Save

2. **Revoke Access (if needed):**
   - Find the CourseAccess record
   - Edit → Status: Revoked
   - Revoked By: [your admin user]
   - Revocation Reason: "Partnership ended"
   - Save

### Workflow 3: Create Cohort for Group Access

1. **Create Cohort:**
   - Admin → Cohorts → Add Cohort
   - Name: "Partner Students - Fluentory"
   - Description: "Students from Fluentory partnership"
   - Save

2. **Add Members:**
   - Admin → Cohort Members → Add Cohort Member
   - Cohort: "Partner Students - Fluentory"
   - User: [select user]
   - Save

3. **Grant Course Access via Cohort:**
   - Admin → Course Accesses → Add Course Access
   - User: [select user]
   - Course: [select course]
   - Access Type: Cohort
   - Cohort: "Partner Students - Fluentory"
   - Save

---

## 🔍 Viewing Access Information

### For a Specific Student:
1. Go to `/admin/myApp/courseaccess/`
2. Filter by User
3. See all their course accesses with:
   - Source (how they got access)
   - Status (unlocked, revoked, expired)
   - Grant date
   - Expiration date
   - Full audit trail

### For a Specific Course:
1. Go to `/admin/myApp/courseaccess/`
2. Filter by Course
3. See all students with access and their access types

### For a Bundle:
1. Go to `/admin/myApp/bundlepurchase/`
2. Filter by Bundle
3. See all purchases and who has access

---

## 🚧 Future Enhancements (Not Yet Built)

These features are planned but not yet implemented in the UI:

1. **Bulk Access Management UI**
   - Grant access to multiple students at once
   - Grant bundle access from member detail page
   - Quick actions in students list

2. **Member Detail Page Enhancements**
   - "Manage Access Rights" modal
   - Add/remove course access
   - Extend access duration
   - Transfer access between accounts

3. **Student Dashboard Updates**
   - "My Courses" section (courses with access)
   - "Available to Unlock" section (courses in bundles they can buy)
   - "Not Available" section (private/invite-only)

4. **Purchase Integration**
   - Automatic access granting on purchase
   - Webhook integration for payment processors
   - Auto-revoke on refund/chargeback

---

## 💡 Tips & Best Practices

1. **Always use CourseAccess records** - Don't rely on CourseEnrollment alone. CourseAccess is the source of truth.

2. **Use meaningful notes** - Add notes to every access grant/revoke for audit trail:
   - "Black Friday Bundle 2025 purchase"
   - "VIP comp - influencer partnership"
   - "Refund processed - customer requested"

3. **Set expiration dates** - For time-limited access, always set `expires_at`:
   - Trial access: 7-30 days
   - Promo access: Until specific date
   - Subscription access: Check subscription status regularly

4. **Use cohorts for groups** - Instead of manually adding 500 students to 12 courses, create a cohort and grant access once.

5. **Bundle everything** - For promos, always create bundles. Makes it easy to:
   - Grant access to all courses at once
   - Track who bought what
   - Revoke access if needed

---

## 🆘 Troubleshooting

### "Why can't this student access the course?"
1. Go to `/admin/myApp/courseaccess/`
2. Filter by User and Course
3. Check:
   - Is there an access record?
   - Is status "unlocked"?
   - Has it expired? (check `expires_at`)
   - Was it revoked? (check status and `revoked_at`)

### "How did this student get access?"
1. Find their CourseAccess record
2. Check the `get_source_display()` or look at:
   - `bundle_purchase` (if from bundle)
   - `cohort` (if from cohort)
   - `granted_by` (if manual)
   - `purchase_id` (if direct purchase)

### "I need to grant access to 100 students"
**Option 1: Use Cohort**
1. Create cohort
2. Add all 100 students to cohort
3. Grant course access with cohort as source (you may need to do this programmatically or extend the system)

**Option 2: Use Bundle**
1. Create bundle with the courses
2. Create BundlePurchase for each student
3. Access is automatically granted

**Option 3: Django Shell (for bulk operations)**
```python
from myApp.utils.access import grant_course_access
from myApp.models import User, Course

users = User.objects.filter(email__endswith='@company.com')
course = Course.objects.get(slug='course-slug')

for user in users:
    grant_course_access(
        user=user,
        course=course,
        access_type='manual',
        notes="Bulk grant - company partnership"
    )
```

---

## 📝 Quick Reference

| Feature | Admin URL | Purpose |
|---------|-----------|---------|
| Bundles | `/admin/myApp/bundle/` | Create course packages |
| Bundle Purchases | `/admin/myApp/bundlepurchase/` | Track purchases & grant access |
| Cohorts | `/admin/myApp/cohort/` | Group students |
| Cohort Members | `/admin/myApp/cohortmember/` | Add users to cohorts |
| Course Access | `/admin/myApp/courseaccess/` | View/manage all access |
| Learning Paths | `/admin/myApp/learningpath/` | Create course sequences |

---

## 🔗 Related Files

- **Models:** `myApp/models.py` (lines 452+)
- **Utilities:** `myApp/utils/access.py`
- **Admin:** `myApp/admin.py` (lines 93+)
- **Migrations:** `myApp/migrations/0007_*.py`

---

## 📞 Need Help?

If you need to:
- Grant bulk access to many students
- Integrate with payment processors
- Build custom UI for access management
- Add cohort-to-course relationships

These features can be built using the existing models and utility functions. The foundation is all there - you just need to build the UI/views on top of it!

---

**Last Updated:** 2025-01-XX
**Version:** 1.0









