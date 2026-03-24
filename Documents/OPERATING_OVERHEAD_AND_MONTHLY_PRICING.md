# Operating Overhead and Monthly Pricing

This document converts the current system design into a practical monthly pricing model.
It maps workflows to cost drivers, applies the existing calculator formulas, and gives a repeatable method for setting price per member.

## 1) System Process Map and Cost Impact

| Process | Main Flow | Cost Impact |
|---|---|---|
| Tenant onboarding | `start_academy` creates tenant, config, admin membership, temporary domain | DB writes, request CPU/memory, support time when onboarding fails |
| Tenant resolution | `TenantMiddleware` resolves tenant by host/domain on each request | Per-request DB/cache lookups, latency pressure at scale |
| Auth and registration | Login/register + membership checks | DB/auth load, abuse risk mitigated by throttling |
| Course browsing and lesson delivery | Course list, lesson views, progress, access checks | Web memory/CPU, DB reads/writes, media egress |
| Creator lesson pipeline | Lesson creation, upload, transcription thread, AI review | Upload bandwidth, temporary storage, web-worker memory, future transcription API cost |
| Dashboard AI course generation | Background thread builds modules/lessons/content via OpenAI | OpenAI token spend, long-running web-process resource usage |
| Lesson chatbot training and chat | Webhook calls for training and message forwarding | Third-party webhook costs, network egress, timeout/retry operational overhead |
| Access and enrollment operations | Grant/revoke course access, bundle/cohort operations | Admin labor, DB writes, support load for entitlement issues |
| Domain and branding operations | Domain verify/set-primary, branding updates | Admin/support time, DNS/domain operations overhead |
| Health, throttling, runtime safeguards | `/healthz`, `/readyz`, protective throttle middleware | Reliability controls, reduced cost spikes from abuse |

Primary implementation references:
- `myApp/views.py`
- `myApp/dashboard_views.py`
- `myApp/middleware.py`
- `myApp/models.py`
- `myProject/urls.py`

## 2) Cost Driver Inventory (Monthly)

### A. Direct platform variable costs
- Memory minutes (web workers, concurrency overhead)
- CPU minutes
- Railway egress GB
- Persistent volume GB-minutes
- AI token usage (input + output)
- Cloud media delivery variable GB (if offloading media)

### B. Direct platform fixed costs
- Cloud media fixed monthly base (if any)
- Non-usage software/services (monitoring, support tools, etc.) - placeholder line item

### C. Operating overhead (business overhead)
- Team salaries/contractors allocated to this product
- Customer support and QA effort
- Founder/management allocation
- Compliance/accounting/legal tooling
- Incident and reliability buffer

Note: this repo has active runtime/environment defaults for web + throttling and OpenAI usage, but several business/finance numbers are external and must stay placeholders until replaced with invoice data.

## 3) Monthly Cost Model (Calculator-Aligned)

The formulas below mirror the existing cost calculator logic in:
- `myApp/templates/calculator/railway_courseforge_cost_calculator_light.html`

### Input variables
- `members`, `dauPct`, `sessionMinutes`
- `workers`, `ramMBPerWorker`, `mediaMBPerActiveUserPerDay`
- `volumeGB`, `uptimeHoursPerDay`
- `cloudSharePct`, `cloudRatePerGB`, `cloudFixedMonthly`
- `aiCoursesPerMonth`, `aiLessonsPerCourse`, `aiQuizzesPerLesson`
- `aiThreadRunsPerActiveUserPerMonth`, `aiInTokensPerRun`, `aiOutTokensPerRun`
- `aiInRatePerMillion`, `aiOutRatePerMillion`
- `monthlyOverhead`, `targetMarginPct`

### Rate constants (from current calculator)
- `memoryRate = 0.000231` USD per GB-minute
- `cpuRate = 0.000463` USD per vCPU-minute
- `egressRate = 0.05` USD per GB
- `volumeRate = 0.00000347` USD per GB-minute
- `minutesMonth = 43,200`

### Formulas
1. `concurrentUsers = members * (dauPct/100) * (sessionMinutes / (uptimeHoursPerDay*60))`
2. `baseRamGB = (workers * ramMBPerWorker) / 1024`
3. `userRamGB = concurrentUsers * 0.005`
4. `memoryCost = (baseRamGB + userRamGB) * (uptimeHoursPerDay*60*30) * memoryRate`
5. `cpuTotal = 0.02 + (concurrentUsers * 0.002)`
6. `cpuCost = cpuTotal * (uptimeHoursPerDay*60*30) * cpuRate`
7. `dauCount = members * (dauPct/100)`
8. `egressGB = (dauCount * mediaMBPerActiveUserPerDay * 30) / 1024`
9. `railwayEgressGB = egressGB * (1 - cloudSharePct/100)`
10. `cloudinaryGB = egressGB * (cloudSharePct/100)`
11. `egressCost = railwayEgressGB * egressRate`
12. `cloudMediaCost = (cloudinaryGB * cloudRatePerGB) + cloudFixedMonthly`
13. `aiLessonRuns = aiCoursesPerMonth * aiLessonsPerCourse`
14. `aiQuizRuns = aiLessonRuns * aiQuizzesPerLesson`
15. `aiThreadRuns = dauCount * aiThreadRunsPerActiveUserPerMonth`
16. `aiTotalRuns = aiLessonRuns + aiQuizRuns + aiThreadRuns`
17. `aiInputTokens = aiTotalRuns * aiInTokensPerRun`
18. `aiOutputTokens = aiTotalRuns * aiOutTokensPerRun`
19. `aiCost = (aiInputTokens/1,000,000)*aiInRatePerMillion + (aiOutputTokens/1,000,000)*aiOutRatePerMillion`
20. `volumeCost = volumeGB * minutesMonth * volumeRate`
21. `platformVariableCost = memoryCost + cpuCost + egressCost + cloudMediaCost + aiCost + volumeCost`
22. `targetRevenue = (platformVariableCost + monthlyOverhead) / (1 - targetMarginPct/100)`
23. `suggestedMonthlyChargePerMember = targetRevenue / members`

## 4) Scenario Outputs (Hybrid Assumptions)

These scenarios are examples using the current formula and clearly labeled assumptions.
Replace with real values monthly.

### Assumed monthly overhead and margin
- Lean: overhead `450`, margin `35%`
- Baseline: overhead `1,200`, margin `40%` (baseline course size set to `25 lessons/course`)
- Growth: overhead `2,800`, margin `45%`

### Cost breakdown and suggested charge
| Scenario | Members | Platform Variable Cost | Overhead | Target Margin | Required Revenue | Suggested Charge / Member |
|---|---:|---:|---:|---:|---:|---:|
| Lean | 100 | 19.64 | 450.00 | 35% | 722.52 | 7.23 |
| Baseline | 500 | 50.21 | 1,200.00 | 40% | 2,083.69 | 4.17 |
| Growth | 1,000 | 114.57 | 2,800.00 | 45% | 5,299.23 | 5.30 |

All currency values above are in USD/month.

### Component-level view (selected)
| Scenario | Memory | CPU | Railway Egress | Cloud Media | AI | Volume |
|---|---:|---:|---:|---:|---:|---:|
| Lean | 7.80 | 0.41 | 0.11 | 10.33 | 0.09 | 0.90 |
| Baseline | 14.70 | 0.46 | 1.21 | 29.51 | 1.64 | 2.70 |
| Growth | 23.62 | 0.58 | 3.30 | 75.82 | 6.01 | 5.25 |

Observation: with current assumptions, cloud media + memory dominate early, while AI becomes material as usage intensity increases.

### AI usage assumptions behind scenario costs
The current model prices AI using runs and tokens. It does not directly price module count.

| Scenario | Courses / Month | Lessons / Course | Quizzes / Lesson | AI Thread Runs / Active User / Month | Total AI Runs / Month |
|---|---:|---:|---:|---:|---:|
| Lean | 1 | 8 | 1 | 6 | 124 |
| Baseline | 3 | 25 | 2 | 10 | 1,475 |
| Growth | 6 | 14 | 2 | 14 | 4,452 |

| Scenario | Input Tokens / Run | Output Tokens / Run | Total Input Tokens / Month | Total Output Tokens / Month | Total Tokens / Month |
|---|---:|---:|---:|---:|---:|
| Lean | 1,200 | 900 | 148,800 | 111,600 | 260,400 |
| Baseline | 1,800 | 1,400 | 2,655,000 | 2,065,000 | 4,720,000 |
| Growth | 2,200 | 1,700 | 9,794,400 | 7,568,400 | 17,362,800 |

Optional module planning assumption for operations only (not part of formula):
- If you plan `4 modules per course`, estimated module volumes are:
  - Lean: `4 modules/month`
  - Baseline: `12 modules/month`
  - Growth: `24 modules/month`

### AI pipeline check against implementation (`dashboard_views.py`)
This is the implemented generation flow in `_generate_course_ai_content`:
- 1x `generate_ai_course_structure` per course
- Per lesson: 1x `generate_ai_lesson_metadata` + 1x `generate_ai_lesson_content` + 1x `generate_ai_quiz`
- 1x `generate_ai_exam` per course
- Plus chatbot training webhook per lesson (`_send_lesson_to_chatbot_webhook`) as non-token network cost

Estimated AI call volume per course (OpenAI calls only):
- `openai_calls_per_course ~= 2 + (3 * lessons_per_course)`
- Baseline at `25 lessons/course` => `77 OpenAI calls/course`

This is why baseline was updated to a larger lesson count: it better reflects your real course build process and AI generation workload.

## 5) Monthly Charging Guidance

Use this policy for each monthly pricing review:

1. Compute `platformVariableCost` from actual usage metrics.
2. Add real `monthlyOverhead` (payroll allocation, tools, support, compliance, incidents).
3. Apply margin target by stage:
   - Early stage: `30-40%`
   - Stabilizing growth: `40-50%`
   - Premium/reliability-heavy offering: `50-60%`
4. Set floor price:
   - `priceFloor = max(platformVariableCost/members + overhead/members, strategic_min_price)`
5. Set recommended charge:
   - `recommended = (platformVariableCost + monthlyOverhead)/(1-margin)/members`
6. Add risk buffer if one or more is true:
   - AI usage volatile month-to-month
   - high support burden per active tenant
   - expected infrastructure step-up (new workers, DB tier, queue layer)

Suggested packaging method:
- Base membership fee from `recommended`.
- Add usage add-ons for high AI chat/generation usage.
- Add enterprise reliability add-on for high-SLA tenants.

## 6) Operating Controls (Budget Discipline)

Align monthly operations with the current Railway cost playbook:
- At 50% spend burn-rate midpoint: right-size top memory services.
- At 75%: pause/freeze non-critical always-on services.
- At 90%: strict mode (minimum replicas, defer non-critical jobs).

Runbook cadence:
- Daily 2-minute check: service memory ranking, idle environments, replica sanity.
- Weekly 15-minute review: top 3 costly services, change reason, one optimization action each.

## 7) Data Collection Checklist (Replace Placeholders)

Update these inputs every month before final pricing:
- Hosting invoice: memory, CPU, egress, storage
- DB/cache/service invoices (if externalized)
- AI usage export: input/output tokens by feature
- Media delivery invoice and GB usage
- Team payroll allocation to product
- Support and incident hours converted to cost
- Tooling subscriptions (monitoring, email, CRM, etc.)
- Refunds/credits and non-recurring adjustments

Once updated, re-run the model and publish:
- final monthly overhead,
- recommended charge/member,
- and variance vs previous month.

## 8) Ownership and Review

- Finance/ops owner: updates costs and overhead values monthly
- Product/engineering owner: updates usage assumptions and scaling changes
- Final approval: founder/lead approves target margin and published price tiers

Review this document monthly or whenever major infrastructure/AI usage patterns change.
