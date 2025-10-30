# Evaluation Methodology: Zero-Bias Approach

**High-Level Design Document**

---

## Core Principle

**Goal:** Evaluate AI-generated applications using only objective, measurable criteria to eliminate subjective bias.

> Traditional evaluation asks: "Is this code well-written?" (subjective)
>
> Our approach asks: "Can an agent deploy this autonomously?" (objective)

This methodology prioritizes **autonomous deployability** over human-assessed quality. If an AI-generated application can build, run, connect to data sources, and serve requests without human intervention, it has succeeded—regardless of code style preferences or subjective quality assessments.

---

## Design Philosophy

### 1. Objectivity Over Subjectivity

**What we measure:**
- Binary outcomes (pass/fail, yes/no)
- Numeric measurements (percentages, counts, timings)
- Checklist-based scores (file presence, command execution)

**What we explicitly avoid:**
- Quality judgments ("Is this good code?")
- Requirement interpretation ("Does this match the prompt?")
- AI-based scoring ("Rate this 1-10")

### 2. Reproducibility as a Requirement

All metrics must be:
- **Deterministic**: Same input → Same output, always
- **Automatable**: No human interpretation required
- **Comparable**: Changes are measurable ("+10%", not "better")
- **CI/CD Ready**: Can run in automated pipelines

### 3. Autonomous Deployability

The guiding question for all metrics:

> **"Can an AI agent deploy this code to production without human help?"**

This frames evaluation around practical functionality rather than abstract code quality.

---

## Bias Minimization Strategy

### Prohibited Approaches

1. **LLM Quality Scoring**
   - ❌ "Rate this code on a scale of 1-5"
   - ❌ "Assess if this meets requirements"
   - ✅ Instead: Binary checks (does it build? does it run?)

2. **Subjective Thresholds**
   - ❌ "Code is 'good' if coverage > 80%"
   - ✅ Instead: Report actual coverage, let stakeholders decide thresholds

3. **Prompt Matching**
   - ❌ "Does this dashboard match the user's request?"
   - ✅ Instead: "Does the API return data?" (verifiable fact)

4. **Aesthetic Judgments**
   - ❌ VLM scoring UI attractiveness
   - ✅ Instead: VLM binary check "Does page render without errors?"

### Allowed AI Use

**VLM for binary verification only:**
- ✅ "Is the page blank?" → yes/no
- ✅ "Are there visible errors?" → yes/no
- ❌ "Is the UI well-designed?" → subjective, prohibited

**LLM for objective command discovery:**
- ✅ "What command installs dependencies?" → discovers from package.json/requirements.txt
- ✅ "How do I run tests?" → analyzes project structure objectively
- ✅ "What's the build command?" → reads configuration files
- ❌ "Is this code well-structured?" → subjective, prohibited

This maintains zero-bias while enabling stack-agnostic evaluation.

---

## The 9-Metric Framework

**See [evals.md](evals.md) for complete implementation details.**

### Core Functionality (Metrics 1-4)
1. **Build Success** - Binary: Does the build complete?
2. **Runtime Success** - Binary: Does the app start and respond?
3. **Type Safety** - Binary: Does type checking pass?
4. **Tests Pass** - Binary + Coverage %: Do tests succeed?

### Domain Integration (Metrics 5-6)
5. **Databricks Connectivity** - Binary: Can app connect to data source?
6. **Data Returned** - Binary: Do endpoints return data?

### User Experience (Metric 7)
7. **UI Renders** - Binary: Does the UI load without errors?

### Developer Experience (Metrics 8-9)
8. **Local Runability** - Checklist (0-5): Ease of local development
9. **Deployability** - Checklist (0-5): Production readiness

**Why 9 metrics?**
- Covers full stack (build → deploy → runtime)
- Balanced: 7 binary + 2 scored metrics
- Minimal viable set (no redundancy)
- Each metric answers a distinct question

---

## Strategic Value

### For AI Code Generation

**Thesis:** AI code generators should produce autonomous deployment candidates.

If human review is required, the automation has failed. Our metrics validate whether an AI can generate production-ready code without human post-processing.

**Benchmark:** What % of AI-generated apps pass all 9 metrics on first try?

### For Continuous Improvement

Objective metrics enable systematic optimization:

1. **A/B Testing**
   - Compare prompt strategies numerically
   - Example: "Approach A: 85% build success vs Approach B: 92%"

2. **Regression Detection**
   - Alert when metrics drop below baselines
   - Example: "Test pass rate dropped from 95% to 78%"

3. **Trend Analysis**
   - Track improvements over time
   - Example: "Average LOC decreased 15% over 3 months"

4. **Cost Efficiency**
   - Track generation cost vs quality trade-offs
   - Example: "Model X costs 2× but has 30% higher success rate"

### For DORA Metrics

Our objective approach directly supports DevOps Research and Assessment (DORA) performance tracking:

- **Deployment Frequency**: % of apps passing deployment checks
- **Lead Time for Changes**: Generation time + build time (measurable)
- **Change Failure Rate**: % failing build/runtime/tests (measurable)
- **Mean Time to Recovery**: Container restart time (measurable)

**See [DORA_METRICS.md](DORA_METRICS.md) for complete DORA integration.**

---

## Design Decisions

### Why Docker-Based Validation?

**Decision:** All build/runtime checks use Docker.

**Rationale:**
- Ensures consistent environment across evaluations
- No dependency on local tool versions (Node.js, Python, etc.)
- Reproducible results on any machine
- Matches production deployment approach

### Why Agentic Evaluation?

**Decision:** Use an AI agent with bash tools to perform evaluation instead of hardcoded scripts.

**Rationale:**
- **Stack Agnostic**: Agent discovers how to build/test/run any framework
- **Zero Maintenance**: No code updates needed for new frameworks
- **Objective**: Agent reads actual files (package.json, requirements.txt, Dockerfile) and executes commands
- **Reproducible**: Same app structure → same evaluation results
- **Zero Bias**: Evaluates what the app *is*, not what we *assume* it should be
- **Truly Agentic**: Agent makes decisions and uses tools, not hardcoded logic

**Implementation:**
```python
EVAL_PROMPT = """
Evaluate all applications in ../app directory using 9-metric framework.

For each app:
1. Read files to discover build/test/run commands
2. Execute commands to verify build, runtime, tests
3. Check for Dockerfile, README, tests, type safety
4. Assign objective scores (binary PASS/FAIL, numeric 0-5)
5. Generate JSON report

Use ONLY bash tools to read files and execute commands.
Be objective: no quality judgments, only measurable facts.
"""

query(EVAL_PROMPT, ClaudeAgentOptions(permission_mode="bypassPermissions"))
```

**Why this maintains zero-bias:**
- Agent doesn't judge quality, only measures objective facts
- Agent reads configuration files like a human would
- Deterministic for same app structure
- No subjective assessment involved
- Agent uses standard tools (bash) to verify builds, tests, runs

**Cost:** ~$0.02-0.05 per full evaluation run (all apps)

### Agent SDK Integration

**Technical Implementation:** The evaluation uses Claude Agent SDK for complementary agent-based metrics (build, run, test, deploy). Key implementation detail (`evaluate_apps.py` lines 18-21):

```python
# Ensure Claude CLI is in PATH for agent SDK
if "/opt/homebrew/bin" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"/opt/homebrew/bin:{os.environ.get('PATH', '')}"
```

This ensures the agent SDK can invoke the Claude CLI when running under `uv run`, which doesn't inherit Homebrew paths by default. Environment variables must be exported (not just sourced) to propagate to subprocess invocations.

**Why this maintains methodology:**
- Agent discovers build/run/test commands by reading project files (package.json, Dockerfile)
- Objective measurement: Did the agent successfully complete the task? (binary)
- No quality judgment - only verifies if an autonomous agent can deploy the app
- Complements direct execution metrics with agentic evaluation

For usage details, see [evals.md](evals.md).

### Why Checklist Scores for DevX?

**Decision:** Local Runability and Deployability use 0-5 checklists.

**Rationale:**
- More nuanced than binary (allows partial credit)
- Still objective (file exists? yes/no)
- Matches real developer workflows
- Avoids subjective quality assessment

### Why No Prompt Matching?

**Decision:** Don't evaluate "Does this match the prompt?"

**Rationale:**
- Highly subjective (requires interpretation)
- Breaks reproducibility (different evaluators → different scores)
- Focuses on wrong question (intent vs capability)
- Better question: "Does this work?" (objective)

### Why Track Generation Metrics?

**Decision:** Track AI cost, tokens, and conversation turns.

**Rationale:**
- Enables cost-benefit analysis (quality vs expense)
- Identifies inefficient generation patterns
- Supports model comparison (GPT-4 vs Claude vs Gemini)
- Tracks AI efficiency improvements over time

---

## Success Criteria

An evaluation framework succeeds if:

1. **Zero Human Judgment Required**
   - Any two people running evals get identical results
   - No "it depends" or "in my opinion" scenarios

2. **Actionable Insights**
   - Failures point to specific, fixable problems
   - Metrics suggest clear improvement paths

3. **Scalable**
   - Can evaluate 1 app or 1000 apps with same approach
   - Automation scales linearly, not exponentially

4. **Industry Standard Compatible**
   - Maps to DORA metrics
   - Supports standard DevOps KPIs
   - CSV export for any analytics tool

---

## Future Directions

### Recently Implemented

1. **AI Generation Metrics** ✅
   - Cost tracking (USD per app)
   - Token usage (input/output)
   - Conversation turns
   - Efficiency (tokens per turn)

2. **UI Renders (Metric 7)** ✅
   - VLM binary check (PASS/FAIL)
   - Screenshot-based verification
   - Zero-bias approach (no quality assessment)
   - Cost: ~$0.001 per app

### Planned Enhancements

1. **Data Returned (Metric 6)**
   - Currently stubbed (returns False)
   - Requires app-specific tRPC procedure knowledge
   - Planned: Introspect router, call first data endpoint

2. **Observability Score** (Metric 10)
   - Logging coverage
   - Error reporting instrumentation
   - Metrics/tracing integration
   - Enables MTTR measurement

3. **Security Score** (Metric 11)
   - Dependency vulnerability scan
   - Secret detection (no hardcoded tokens)
   - HTTPS enforcement
   - Auth/authz coverage

4. **Performance Baselines**
   - Response time percentiles (p50, p95, p99)
   - Memory usage under load
   - Database query efficiency

### Research Questions

1. **What is the theoretical limit of AI autonomous deployability?**
   - Can we reach 100% success rate?
   - What bottlenecks prevent full automation?

2. **How do generation cost and quality correlate?**
   - Does more expensive generation = higher quality?
   - What's the optimal cost/quality point?

3. **Can we predict success rate from prompt characteristics?**
   - Do certain prompt patterns yield better results?
   - Machine learning on prompt → success prediction?

---

## References

- **Quick Reference**: [evals.md](evals.md) - Metric definitions, output formats, usage
- **DORA Integration**: [DORA_METRICS.md](DORA_METRICS.md) - DevOps metrics mapping
- **Implementation**: `cli/evaluate_all.py`, `cli/evaluate_app.py`, `cli/bulk_run.py`

---

**Last Updated:** October 20, 2025
**Framework Version:** 1.0 (9 metrics + generation tracking)
**Evaluation Cost:** ~$0.001/app (VLM only)
**Generation Cost:** ~$0.74/app (empirical)
