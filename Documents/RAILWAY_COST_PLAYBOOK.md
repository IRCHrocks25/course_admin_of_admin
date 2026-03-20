# Railway Cost Playbook (Course Admin of Admin)

This playbook is optimized for this project where memory minutes are the primary cost driver.
Use it as an operating SOP for keeping monthly spend predictable.

## 1) Cost Goal and Trigger Points

- Monthly target: keep actual spend <= 70% of Railway estimate by mid-cycle.
- Trigger at 50%: review top memory-consuming services and right-size.
- Trigger at 75%: freeze non-critical always-on services.
- Trigger at 90%: enable strict mode (minimum replicas, pause preview envs, defer non-critical jobs).

## 2) Daily 2-Minute Routine

1. Open Railway project metrics and sort services by memory cost.
2. Confirm only required services are running.
3. Stop idle non-production services (staging/dev/preview).
4. Verify replica counts are still at intended baseline.
5. Record any spike and owner in the weekly cost log.

## 3) Service Sizing Policy

- Start each service at the smallest plan that meets baseline SLO.
- Scale up temporarily for load/tests/migrations, then scale back the same day.
- Keep replicas at 1 unless there is a measured reliability/load requirement.
- Avoid over-provisioning "just in case"; rely on scaling events and monitoring.

## 4) Process Rules for This Django App

- `DEBUG` must stay `False` in Railway production.
- Set `WEB_CONCURRENCY` explicitly per environment (start with `2`, test with `1` if stable).
- Keep long-running heavy jobs out of the web process where possible.
- Use release phase only for required tasks (`migrate`, `collectstatic`, cache table setup).
- Avoid running optional workers/schedulers 24/7 unless they provide active customer value.

## 5) Preview and Environment Hygiene

- Auto-delete preview environments after PR close/merge.
- Limit number of simultaneous previews.
- Use shared lower-cost backing services for previews when acceptable.
- Ensure old projects/services are archived or removed.

## 6) Storage and Data Controls

- Remove unused volumes and orphaned services.
- Keep only required retention for logs/backups in non-prod.
- Ensure media/static strategy is intentional (CDN/object store where possible).

## 7) Weekly Cost Review (15 Minutes)

Assign one owner per service and review:

1. Top 3 services by memory spend this week.
2. What changed (deploy, traffic, concurrency, new process)?
3. One concrete optimization action per expensive service.
4. Confirm action completion in next review.

## 8) Incident Mode (When Spend Spikes)

Execute in order:

1. Stop non-critical environments immediately.
2. Reduce replicas for non-core services to minimum.
3. Decrease `WEB_CONCURRENCY` for web service if latency/error budget permits.
4. Disable/slow non-essential background jobs.
5. Re-check memory trend after 30-60 minutes.

## 9) Recommended Railway Environment Variables

Set these explicitly in Railway production:

- `DEBUG=False`
- `WEB_CONCURRENCY=2` (consider `1` if memory pressure remains and throughput is acceptable)
- `GUNICORN_WORKER_CLASS=gthread`
- `GUNICORN_THREADS=2`
- `GUNICORN_TIMEOUT=120`
- `GUNICORN_GRACEFUL_TIMEOUT=30`
- `GUNICORN_MAX_REQUESTS=1000`
- `GUNICORN_MAX_REQUESTS_JITTER=100`
- `LOG_LEVEL=info` (or `warning` if logs are noisy)
- `ENABLE_PROTECTIVE_THROTTLE=True`

Optional per environment:

- `CACHE_BACKEND=db` for persistent shared cache behavior
- `CACHE_BACKEND=locmem` for temporary/preview setups where persistence is not required
- `THROTTLE_LOGIN_PER_MIN=30`
- `THROTTLE_REGISTER_PER_MIN=12`
- `THROTTLE_AI_GENERATE_PER_MIN=8`
- `THROTTLE_TRANSCRIBE_PER_5MIN=6`

## 10) Automatic Protection Checklist (Railway + App)

1. Configure Railway health check path to `/healthz/`.
2. Configure readiness/startup probe path to `/readyz/` (if available in your plan/workflow).
3. Enable Railway autoscaling with max replicas cap (to control cost blast radius).
4. Add Railway budget alerts at 50/75/90%.
5. Keep app-level throttles enabled to shed abusive bursts before worker exhaustion.

Suggested autoscaling guardrails:

- Scale out when p95 latency > 1.5s for 10 minutes OR CPU > 75% for 10 minutes.
- Scale in when p95 latency < 700ms and CPU < 40% for 20 minutes.
- Keep max replica cap to a spend-safe value (for example 2-3 for early stage).

## 11) Capacity Estimation Worksheet

Use this to estimate safe throughput before launch:

- `effective_concurrency = WEB_CONCURRENCY * GUNICORN_THREADS`
- `estimated_rps = effective_concurrency / p95_request_seconds`

Example with current defaults:

- `WEB_CONCURRENCY=2`, `GUNICORN_THREADS=2` => `effective_concurrency = 4`
- If p95 login/create request is `0.5s`, estimated safe throughput is about `8 req/s`
- If p95 request is `1.0s`, estimated safe throughput is about `4 req/s`

Approximate "active users at once" conversion:

- If a typical active user sends 1 request every 10 seconds, then:
- `active_users ~= estimated_rps * 10`
- So `4-8 req/s` maps to roughly `40-80` active users for mixed normal usage

For creator-heavy or AI/transcription-heavy usage, assume much lower throughput and test separately.

## 12) Ownership Template

For each running service, keep:

- Service name
- Primary owner
- Minimum safe size
- Normal replica count
- Can be paused? (yes/no)
- Last right-sizing date
- Next optimization task

---

Keep this playbook lightweight: if a rule is repeatedly ignored, simplify it rather than adding more policy.
