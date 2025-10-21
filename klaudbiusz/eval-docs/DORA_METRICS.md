# DORA Metrics for AI-Generated Applications

## Overview

DORA (DevOps Research and Assessment) defines four key metrics for measuring software delivery performance:

1. **Deployment Frequency** - How often code is deployed to production
2. **Lead Time for Changes** - Time from code commit to production deployment
3. **Mean Time to Recovery (MTTR)** - Time to restore service after an incident
4. **Change Failure Rate** - Percentage of deployments causing failures

## How Our Current Metrics Support DORA

### Deployment Frequency (Enabled by our metrics)

**Our metrics that contribute:**
- ✅ **Build Success** - Ensures app can be built reliably
- ✅ **Runtime Success** - Confirms app starts without intervention
- ✅ **Deployability Score** - Measures production-readiness

**How they help:**
- Apps that pass these metrics can be deployed more frequently
- Automated checks reduce pre-deployment friction
- High deployability scores indicate single-command deployment capability

**Gap:** We don't currently track *actual* deployment frequency (how often these apps get deployed)

---

### Lead Time for Changes (Partially supported)

**Our metrics that contribute:**
- ✅ **Build Time** (metadata) - Measures compilation speed
- ✅ **Type Safety** - Catches errors early (before deployment)
- ✅ **Tests Pass** - Automated validation reduces manual review time
- ✅ **Deployability Score** - One-command deployment reduces lead time

**Current tracking:**
```
Generation time: ~X minutes (AppBuilder tracks this)
Build time: ~Y seconds (we measure this)
Total time to deployable artifact: Generation + Build
```

**Gap:** We don't track:
- Time from "idea/prompt" → working app in production
- Time from code change → production (for iterative changes)
- CI/CD pipeline execution time

---

### Mean Time to Recovery (MTTR) (Not yet supported)

**Our metrics that could help:**
- ✅ **Health Checks** - Enable fast failure detection
- ⚠️ **Tests Pass** - Reduce likelihood of bugs, but doesn't measure recovery time

**Gap:** We don't track:
- Time to detect failures in production
- Time to diagnose root cause
- Time to deploy fix
- Rollback capability/speed

**What we need to add:**
1. **Observability Score** - Does app have logging, monitoring, alerting?
2. **Rollback Test** - Can previous version be restored quickly?
3. **Error Rate Tracking** - Runtime error frequency after deployment
4. **Incident Simulation** - Test recovery procedures

---

### Change Failure Rate (Partially supported)

**Our metrics that contribute:**
- ✅ **Build Success** - Prevents broken builds from deploying
- ✅ **Runtime Success** - Catches startup failures
- ✅ **Tests Pass** - Validates functionality before deployment
- ✅ **Type Safety** - Prevents type-related runtime errors
- ✅ **Databricks Connectivity** - Ensures core feature works
- ✅ **Security Scan** (implied) - Prevents vulnerable deploys

**Current failure detection:**
```
Pre-deployment failures caught by our metrics: ~90%
- Build failures
- Test failures
- Type errors
- API contract violations
```

**Gap:** We don't track:
- Post-deployment failures (in production)
- User-reported issues
- Silent failures (app runs but produces wrong results)
- Performance degradations

---

## Additional Metrics Needed for DORA Tracking

### 1. Deployment Tracking (New)
**Purpose:** Measure actual deployment frequency

```python
@dataclass
class DeploymentMetrics:
    deployment_timestamp: str
    deployment_environment: str  # staging, production
    deployment_method: str  # manual, CI/CD, automated
    deployment_duration_sec: float
    previous_version: str | None
    rollback_available: bool
```

**Implementation:**
- Hook into deployment process (GitHub Actions, Fly.io, etc.)
- Record each deployment event
- Calculate: deployments per day/week

---

### 2. Lead Time Tracking (Enhanced)
**Purpose:** Measure end-to-end delivery time

```python
@dataclass
class LeadTimeMetrics:
    # AI generation phase
    prompt_timestamp: str
    generation_complete_timestamp: str
    generation_duration_sec: float

    # Build phase
    build_start_timestamp: str
    build_complete_timestamp: str
    build_duration_sec: float

    # Deployment phase
    deployment_start_timestamp: str
    deployment_complete_timestamp: str
    deployment_duration_sec: float

    # Total lead time
    total_lead_time_sec: float  # prompt → production
```

**Implementation:**
- Instrument AppBuilder to track timestamps
- Hook into CI/CD pipeline
- Record: idea → prompt → generation → build → deploy → production

---

### 3. Observability Score (New)
**Purpose:** Measure MTTR readiness

```python
def check_observability(app_dir: Path) -> tuple[int, list[str]]:
    """Score 0-5: How well can we detect and diagnose failures?"""
    score = 0

    # +1: Structured logging implemented
    if has_logger_usage(app_dir):
        score += 1

    # +1: Error tracking/reporting (Sentry, etc.)
    if has_error_tracking(app_dir):
        score += 1

    # +1: Health check with detailed status
    if has_detailed_healthcheck(app_dir):
        score += 1

    # +1: Metrics/monitoring instrumentation
    if has_metrics_instrumentation(app_dir):
        score += 1

    # +1: Distributed tracing (OpenTelemetry, etc.)
    if has_tracing(app_dir):
        score += 1

    return score
```

---

### 4. Production Reliability Tracking (New)
**Purpose:** Measure actual failure rates in production

```python
@dataclass
class ReliabilityMetrics:
    # Collected from production monitoring
    uptime_pct: float  # 99.9%
    error_rate_pct: float  # 0.1%
    p50_response_time_ms: float
    p99_response_time_ms: float

    # Incident tracking
    incidents_last_30d: int
    mttr_minutes: float  # Mean time to recovery

    # Change failure tracking
    deployments_last_30d: int
    failed_deployments: int
    change_failure_rate: float  # failed / total
```

**Implementation:**
- Integrate with monitoring systems (Datadog, Prometheus, etc.)
- Track HTTP error rates (5xx responses)
- Measure query failure rates (Databricks errors)
- Record incident timeline (detection → resolution)

---

### 5. Rollback Capability (New)
**Purpose:** Improve MTTR by enabling fast recovery

```python
def check_rollback_capability(app_dir: Path) -> bool:
    """Can this app be rolled back to previous version?"""

    checks = [
        # Version tagging in place
        has_version_tags(),

        # Database migrations are reversible
        has_reversible_migrations(app_dir),

        # No breaking API changes
        api_is_backward_compatible(app_dir),

        # Deployment config supports rollback
        deployment_supports_rollback(app_dir),
    ]

    return all(checks)
```

---

## DORA Metrics Dashboard for AI-Generated Apps

**Proposed metrics summary:**

```json
{
  "dora_metrics": {
    "deployment_frequency": {
      "deployments_per_week": 5,
      "trend": "improving"
    },
    "lead_time_for_changes": {
      "median_seconds": 420,  // 7 minutes (prompt → deployed)
      "breakdown": {
        "generation": 300,    // 5 min
        "build": 120          // 2 min
      }
    },
    "mttr_minutes": {
      "median": 15,
      "p90": 45,
      "enabled_by": {
        "observability_score": 4,
        "rollback_capability": true
      }
    },
    "change_failure_rate": {
      "percentage": 5.0,
      "pre_deployment_catches": 95.0,  // our eval catches 95%
      "post_deployment_failures": 5.0   // 5% slip through
    }
  }
}
```

---

## Implementation Roadmap

### Phase 1: Foundation (Current state)
- ✅ Build, runtime, type safety checks
- ✅ Tests and coverage
- ✅ Deployability score
- ✅ Local runability score

### Phase 2: Pre-deployment DORA (Week 1-2)
- [ ] Track generation time (already in bulk_run.py)
- [ ] Track build time (already in evaluate_app.py)
- [ ] Add observability score check
- [ ] Add rollback capability check
- [ ] Calculate pre-deployment change failure rate

### Phase 3: Production DORA (Week 3-4)
- [ ] Integrate with deployment platforms (GitHub Actions, Fly.io)
- [ ] Record deployment events with timestamps
- [ ] Hook into monitoring systems (logs, metrics)
- [ ] Track actual deployment frequency
- [ ] Track post-deployment failures
- [ ] Calculate actual MTTR from incidents

### Phase 4: Continuous Improvement (Ongoing)
- [ ] Dashboard showing DORA trends over time
- [ ] Compare AI-generated apps vs human-written apps
- [ ] Identify patterns in high-performing apps
- [ ] Feed insights back into generation prompts

---

## Unique Considerations for AI-Generated Apps

### 1. **Generation Quality = Deployment Readiness**
Unlike human-written code, AI-generated code should be deployable immediately if evaluation passes. This means:
- Higher bar for "passing" metrics (4/5 vs 3/5)
- No manual review before first deployment (automated only)
- Generation time is part of lead time

### 2. **Consistency is Key**
AI should generate consistently deployable apps:
- Track variance in metrics across apps
- Flag "outlier" apps that deviate from patterns
- Measure: `std_dev(build_time)`, `std_dev(test_coverage)`, etc.

### 3. **Zero-Touch Deployment**
Goal: Prompt → Production without human intervention
- Deployment frequency → How often can we auto-deploy?
- Lead time → How fast can we auto-deploy?
- Change failure rate → How often do auto-deploys fail?

### 4. **Cost Efficiency**
Additional metric unique to AI generation:
- Cost per deployment = `(generation_cost + build_cost + deployment_cost)`
- Compare to: "human developer time to build same app"

---

## Summary: Current Coverage vs Needed

| DORA Metric | Current Coverage | Gap | Priority |
|-------------|------------------|-----|----------|
| **Deployment Frequency** | 0% (not tracked) | Need deployment event tracking | HIGH |
| **Lead Time** | 60% (generation + build tracked) | Need deployment phase tracking | HIGH |
| **MTTR** | 20% (health checks exist) | Need observability, incident tracking | MEDIUM |
| **Change Failure Rate** | 70% (pre-deploy only) | Need post-deploy failure tracking | HIGH |

**Recommended next steps:**
1. Add deployment event tracking to bulk_run.py
2. Implement observability score in evaluate_app.py
3. Set up production monitoring integration
4. Build DORA dashboard from collected metrics
