# Multi-Tenant Migration - Phase 1

Last updated: 2026-03-18  
Status: Implementation guide (Phase 1 only)

## Goal of Phase 1

Introduce tenant ownership in the data model without changing runtime routing yet.  
At the end of Phase 1, the app still behaves like a single-tenant product from the user perspective, but the database is ready for tenant-scoped logic.

## Scope (In)

- Add `Tenant` and `TenantConfig` models
- Add tenant ownership (`tenant` FK) to core domain models
- Backfill all existing records into a default tenant
- Convert global slug uniqueness to tenant-scoped uniqueness where needed
- Add indexes and guard rails for tenant filtering
- Keep existing URLs and behavior working (no subdomain routing yet)

## Scope (Out)

- Tenant middleware / subdomain resolution
- Super-admin UI
- Tenant-branded theming
- Tenant-specific domain handling (custom domains, dynamic CSRF, SSL)
- Tenant-specific API key runtime wiring in views

---

## 1) Phase 1 Design Decisions (Must lock before coding)

### 1.1 User model strategy for now

Use existing Django `User` model unchanged in Phase 1.  
Create tenant linkage later in Phase 2/3 via either:

- `TenantMembership(user, tenant, role)` (recommended), or
- tenant FK on profile model if one is introduced.

Why now: avoids auth-breaking migration during the core data ownership rollout.

### 1.2 Default tenant bootstrap

Create one bootstrap tenant for all existing data, for example:

- `name`: "Default Tenant"
- `slug`: "default"
- `is_active`: true

All existing rows in tenantized tables are assigned to this tenant during backfill.

### 1.3 Key uniqueness policy

Change global uniqueness to tenant-scoped uniqueness where collisions are expected across white-label clients:

- `Course.slug` -> unique per (`tenant`, `slug`)
- `Bundle.slug` -> unique per (`tenant`, `slug`)
- `Lesson` already unique by (`course`, `slug`) and inherits tenant through `course`

For fields currently globally unique but likely tenant-owned (`Bundle.name`, `Cohort.name`), convert to tenant-scoped uniqueness in this phase or phase 1.5 (same release train).

---

## 2) Models to Add

## 2.1 `Tenant`

```python
class Tenant(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    custom_domain = models.CharField(max_length=255, unique=True, null=True, blank=True)
    logo = models.ImageField(upload_to='tenant_logos/', null=True, blank=True)
    primary_color = models.CharField(max_length=7, default='#3B82F6')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
```

## 2.2 `TenantConfig`

Prefer storing non-secret defaults only in this table. For sensitive keys, use encrypted fields or external secret manager.

```python
class TenantConfig(models.Model):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='config')
    chatbot_webhook = models.URLField(blank=True)
    vimeo_team_id = models.CharField(max_length=255, blank=True)
    accredible_issuer_id = models.CharField(max_length=255, blank=True)
    features = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

If you must store API keys in DB, use encrypted field support and strict admin permissions.

---

## 3) Existing Models Requiring `tenant` FK (Minimum Set)

Add:

```python
tenant = models.ForeignKey('Tenant', on_delete=models.CASCADE, related_name='...')
```

to these models:

- Content:
  - `Course`, `Module`, `Lesson`, `CourseResource`
- Assessment:
  - `LessonQuiz`, `LessonQuizQuestion`, `LessonQuizAttempt`
  - `Exam`, `ExamQuestion`, `ExamAttempt`
- Learning tracking:
  - `UserProgress`, `CourseEnrollment`, `FavoriteCourse`
- Certification:
  - `Certification`
- Access control:
  - `CourseAccess`, `Bundle`, `BundlePurchase`, `Cohort`, `CohortMember`, `LearningPath`, `LearningPathCourse`

Note:

- Child models technically infer tenant through parent relation, but explicit tenant on children improves query safety and indexing.  
- If minimizing migration risk/size, you can tenantize parent/root models first, then add child tenant columns in Phase 1b.

---

## 4) Migration Sequence (Safe Order)

## 4.1 Pre-migration cleanup

1. Remove duplicate `Cohort` class definition in `models.py`  
2. Run tests / smoke checks before tenant changes  
3. Backup production DB snapshot

## 4.2 Schema Migration A - add tenant models

1. Create `Tenant` and `TenantConfig` tables  
2. Create default tenant row via data migration

## 4.3 Schema Migration B - add nullable tenant FKs

1. Add nullable `tenant` FK to all in-scope models (`null=True`, `blank=True`)  
2. Add non-unique indexes for tenant-heavy tables, e.g.:
   - `(tenant, status)` on `Course`
   - `(tenant, user)` on progress/access tables
   - `(tenant, slug)` on slugged tables

## 4.4 Data Migration C - backfill tenant values

Backfill in deterministic order to avoid null references:

1. Root entities first (`Course`, `Bundle`, `Cohort`, `LearningPath`)  
2. Child entities from parent tenant:
   - `Module/Lesson/CourseResource` from `course.tenant`
   - quiz/exam children from their parent object tenant
3. User-bound records:
   - `CourseEnrollment`, `FavoriteCourse`, `Certification`, `CourseAccess`, `UserProgress`, etc. from related `course/lesson/exam` tenant

After backfill, assert zero null tenant rows in all migrated tables.

## 4.5 Schema Migration D - enforce constraints

1. Set `tenant` FK to non-null on all tenantized models  
2. Update uniqueness:
   - `Course`: drop global `slug` unique, add unique constraint on (`tenant`, `slug`)
   - `Bundle`: drop global `slug` unique, add unique constraint on (`tenant`, `slug`)
3. Add/adjust unique constraints for tenant-owned naming fields if desired:
   - (`tenant`, `name`) for `Cohort` / `Bundle` (recommended)

## 4.6 Post-migration verification

1. `makemigrations` + `migrate` succeeds on empty and existing DB  
2. Existing app flows still work unchanged on default tenant data  
3. Admin can still read/write courses/lessons/users

---

## 5) Data Migration Strategy (Existing Production Data)

## 5.1 Backfill rules

- Every existing row gets `tenant = default_tenant`
- No business logic changes yet
- Preserve IDs/slugs/content exactly (except constraint changes)

## 5.2 Collision handling

Before enforcing tenant-scoped uniqueness, verify:

- no duplicate slugs inside the same tenant backfill group (should not happen with one default tenant if old global uniqueness held)
- if duplicate `name` constraints are introduced (`Cohort`, `Bundle`), pre-audit and auto-rename collisions if needed

## 5.3 Rollback posture

- Keep DB snapshot before migration
- Use reversible migration blocks where possible
- If rollout fails after non-null enforcement, restore snapshot and patch migration script

---

## 6) Code Changes in Phase 1 (Minimal Runtime Impact)

Keep runtime behavior stable while making code tenant-ready:

- Add tenant field in admin list displays/filters where relevant
- In model creation paths, set tenant explicitly (for now default tenant or inherited parent tenant)
- Add helper util:
  - `get_default_tenant()` for transitional code paths
- Avoid enabling tenant-based request filtering until middleware exists (Phase 2)

### 6.1 Transitional helper example

```python
def get_default_tenant():
    return Tenant.objects.get(slug='default')
```

Use this only as a temporary bridge and remove once request-based tenant resolution is live.

---

## 7) Test Plan (Zero-Regression + Data Integrity)

## 7.1 Migration tests

- Migration applies on:
  - brand-new DB
  - copy of current populated DB
- All tenantized tables have zero null `tenant_id` post-migration
- Constraint checks pass (especially new unique constraints)

## 7.2 Core behavior smoke tests

- Login/logout still works
- Courses list and course detail still render
- Lesson progress updates still write correctly
- Dashboard CRUD for course/lesson/quiz still works
- Access grant/revoke flows still operate
- Existing analytics pages load without exceptions

## 7.3 Data integrity tests

- `Course.tenant == Lesson.course.tenant` consistency
- `UserProgress.tenant == UserProgress.lesson.tenant`
- `CourseAccess.tenant == CourseAccess.course.tenant`
- `Certification.tenant == Certification.course.tenant`

---

## 8) Definition of Done (Phase 1 Exit Criteria)

Phase 1 is complete only when all are true:

1. `Tenant` and `TenantConfig` exist in production DB
2. All in-scope domain models have non-null tenant FK
3. Default tenant backfill completed with zero null tenant rows
4. Slug uniqueness moved to tenant-scoped constraints
5. Duplicate `Cohort` model definition removed
6. Existing single-tenant behavior verified by smoke tests
7. Documentation updated for Phase 2 handoff

---

## 9) Hand-off to Phase 2

Phase 2 should start immediately after this with:

- `TenantMiddleware` request resolution
- host/subdomain strategy
- tenant-scoped queryset enforcement in views/services
- dynamic host/origin policy for multi-domain operation

