# Course Category and Sorting Logic (Admin to Student View)

This document explains how category and course ordering are handled end-to-end:

- where admins set/edit category and order
- how bulk updates work
- how student-facing pages sort and group courses

It reflects the current behavior in `myApp`.

## 1) Core Data Fields

Course ordering and grouping are driven by two `Course` model fields:

- `category` (`CharField`, nullable/blank)
- `display_order` (`PositiveIntegerField`, default `0`)

Defined in `myApp/models.py`.

`display_order` rule is simple: **lower number appears earlier**.

## 2) Admin-Side Editing Points

## A) Add Course flow

In `dashboard_add_course()` (`myApp/dashboard_views.py`):

- Reads `category` from form (`name="category"`)
- Reads `display_order` from form (`name="display_order"`)
- Coerces order to non-negative integer via `max(0, int(...))`
- Falls back to `0` if invalid
- Saves both fields when creating `Course`

UI input lives in `myApp/templates/dashboard/add_course.html` (Step 2):

- Category text field (optional)
- Display Order numeric input with helper text

## B) Edit Course flow

In `dashboard_course_detail()` (`myApp/dashboard_views.py`):

- Updates `course.category` from POST
- Updates `course.display_order` from POST
- Invalid order input keeps previous/fallback value safely
- Saves course

UI is in `myApp/templates/dashboard/course_detail.html`:

- Category field
- Display Order field with “Lower numbers show first” note

## C) Bulk updates from Courses list

In `dashboard_courses()` (`myApp/dashboard_views.py`), POST bulk actions:

1. `set_category`
   - Applies one category value across selected courses
   - Blank value clears category (`None`)

2. `set_display_order`
   - Takes `bulk_order_start`
   - Sorts selected courses by `name`, `id`
   - Assigns sequential display orders (`start + index`)
   - Uses `bulk_update` for one batched DB write

UI for this is in `myApp/templates/dashboard/courses.html`.

## 3) Admin List Ordering (Manage Courses)

When showing admin courses (`dashboard_courses()` GET):

- queryset order is:
  - `display_order` ASC
  - `name` ASC
  - `created_at` DESC (tie-breaker)

So in dashboard cards, courses appear in the same order students see in custom-sorted catalog mode.

## 4) Student-Facing Sorting Behavior

All student catalog/dashboard routing starts at:

- `courses()` in `myApp/views.py`
- renders `learning_hub.html` (current unified page)

## A) Guest (not logged in) catalog

Handled by `_courses_guest()`:

- Base filter: `status='active'` and current tenant
- Optional search by name (`name__icontains`)
- Sort mode from `?sort=`:
  - `name` -> `order_by('name', '-created_at')`
  - default/custom -> `order_by('display_order', 'name', '-created_at')`

So guests can switch between alphabetical and custom ordering.

## B) Logged-in learner dashboard

Handled by `_courses_authenticated()`:

- Builds learner-specific lists (`my_courses_data`, unlockable courses, progress)
- Then performs custom in-memory sort for `my_courses_data`:
  1. categorized courses first, uncategorized last
  2. category name (A-Z, case-insensitive)
  3. `display_order` ASC
  4. course name (A-Z)

Code key:

- uncategorized check: `(course.category or '').strip()`
- fallback label: `Uncategorized`

This means logged-in users see grouped-by-category style ordering, then manual sequence within category.

## 5) Category Filter Behavior for Logged-in Users

Still in `_courses_authenticated()`:

- Builds available category chips from current `my_courses_data`
- Includes `Uncategorized` bucket when category is empty
- Normalizes case for lookup/filtering
- Query param: `?category=<name>`

Filtering applies **after** sorting.

Favorites filter (`?favorites=true`) also applies on top.

UI chips are rendered in `myApp/templates/learning_hub.html`.

## 6) How Category Is Displayed on Student Side

In `learning_hub.html`:

- Guest cards show category pill (`course.category|default:"Uncategorized"`)
- Logged-in course cards also show category in metadata row

So empty categories never look blank to students; they render as `Uncategorized`.

## 7) Tenant Scoping Considerations

All course lists are tenant-scoped via `request.tenant` logic:

- Admin dashboard course management is scoped by `_get_dashboard_tenant()`
- Student catalog/dashboard is scoped by `request.tenant` in `courses()`

Sorting/category logic runs **inside** that tenant scope.

## 8) Important Note: Django Admin vs Dashboard Admin

`CourseAdmin` in `myApp/admin.py` currently does **not** expose `category` or `display_order` in `list_display`/custom ordering.

Practical implication:

- Operational category/order management is intended through dashboard pages:
  - `dashboard_add_course`
  - `dashboard_course_detail`
  - `dashboard_courses` bulk tools

## 9) End-to-End Flow (Quick Summary)

1. Admin sets category/order on create/edit, or bulk-updates from courses list.
2. Values are persisted on `Course.category` and `Course.display_order`.
3. Guest catalog can sort by custom (display order) or by name.
4. Logged-in learners get category-grouped ordering + optional category/favorites filters.
5. Empty category always falls back to `Uncategorized` in UI.

