# Access Control - Quick Reference Card

## 🎯 Where to Find Everything

### Django Admin URLs
```
/admin/myApp/bundle/              → Create course bundles
/admin/myApp/bundlepurchase/      → Track purchases & auto-grant access
/admin/myApp/cohort/              → Create student groups
/admin/myApp/cohortmember/        → Add users to groups
/admin/myApp/courseaccess/       → View/manage ALL access records
/admin/myApp/learningpath/        → Create course sequences
```

---

## ⚡ Common Tasks

### Grant Access to One Student
1. `/admin/myApp/courseaccess/` → Add Course Access
2. Select User, Course, Access Type
3. Save

### Create Black Friday Bundle
1. `/admin/myApp/bundle/` → Add Bundle
2. Name: "Black Friday 2025"
3. Select courses
4. Save

### Grant Bundle Access
1. `/admin/myApp/bundlepurchase/` → Add Bundle Purchase
2. Select User & Bundle
3. Add Purchase ID
4. Save → ✅ Access auto-granted!

### Create Student Group
1. `/admin/myApp/cohort/` → Add Cohort
2. Name: "VIP Mastermind"
3. Save
4. `/admin/myApp/cohortmember/` → Add members

### Revoke Access
1. `/admin/myApp/courseaccess/` → Find record
2. Edit → Status: "Revoked"
3. Add reason
4. Save

---

## 🔍 Troubleshooting

**Student can't access course?**
→ Check `/admin/myApp/courseaccess/` → Filter by User & Course

**How did they get access?**
→ Look at CourseAccess record → Check "Source" column

**Need bulk access?**
→ Use Bundle or Cohort, or run Python script in Django shell

---

## 📚 Full Documentation
See `ACCESS_CONTROL_GUIDE.md` for complete details.









