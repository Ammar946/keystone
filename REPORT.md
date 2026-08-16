# Engineering Report: Computer-Use Automation System

**Author**: Engineering Submission
**Repository**: Public GitHub Repository  
**Format**: Architectural Design & Technical Write-Up  

---

## 1. Architecture

### Core Topology & Paradigm
Legacy banking systems (core processors, teller platforms, servicing tools) lack APIs, yet require deterministic reliability, sub-second execution speeds, and strict regulatory safety. Our system implements a strict two-stage lifecycle:
1. **Discovery (Model in the Loop)**: An LLM-driven discovery agent explores an application surface in response to a natural language goal, records its actions, discovers multi-strategy locators, asserts invariants, and compiles the flow into a typed **Capability Artifact**.
2. **Deterministic Replay (Zero LLM in Production)**: When an AI agent invokes the capability in production, the flow executes through a **Surface Adapter** without invoking an LLM. This eliminates model inference costs, token latency, and probabilistic hallucinations.

```
+--------------------------------------------------------------------------------+
|                                1. DISCOVERY                                    |
|  Goal + URL -> Discovery Agent (LLM) -> SurfaceAdapter -> Live Target Surface  |
|                                     |                                          |
|                                     v                                          |
|                         Artifact Compiler & Validator                          |
+-------------------------------------+------------------------------------------+
                                      |
                                      v
                       [ Capability Artifact (.json) ]
                                      |
+-------------------------------------+------------------------------------------+
|                            2. PRODUCTION REPLAY                                |
|  Calling Agent -> Replay Engine (Zero LLM) -> Pre-Action Policy Gate           |
|                                            -> Scoped Locator Resolver          |
|                                            -> SurfaceAdapter -> Live Session   |
|                                            -> Checkpoint & Outcome Classifier  |
|                                            -> Structured Business Outputs      |
+-------------------------------------+------------------------------------------+
                                      |
                           (Stuck / Irreversible)
                                      v
+--------------------------------------------------------------------------------+
|                        3. SAME-SESSION HITL TAKEOVER                           |
|  Live Session (session_id) -> Operator Console -> Human Actions Log -> Resume  |
+--------------------------------------------------------------------------------+
```

### Key Architectural Decisions & Trade-Offs

- **The Surface Adapter Boundary (`SurfaceAdapter`)**: Rather than coupling the replay engine directly to Playwright or browser APIs, we introduced an abstract `SurfaceAdapter` protocol. The Capability Artifact and Replay Engine operate purely against surface-neutral primitives (`observe()`, `resolve_target()`, `click()`, `type_text()`, `read_text()`, `capture_screenshot()`). `PlaywrightSurfaceAdapter` serves as the web implementation, while desktop and accessibility adapters plug into the same contract.
- **Pre-Action Policy Gate**: Safety checks are not merely post-hoc log filters; they run as an active pre-execution gate before every action. If an action is high-risk (e.g. core ledger binding), it cannot reach the surface adapter without an explicit authorization token or human intervention.
- **Single-Process vs. Distributed Queues**: We deliberately chose an in-process, asynchronous Python runtime using Pydantic v2 and Playwright. This maximizes operational simplicity and eliminates distributed state synchronization bottlenecks while maintaining clean service boundaries.

---

## 2. Artifact Schema

The Capability Artifact is an executable contract between calling AI agents and target application interfaces. It is explicitly versioned, human-reviewable, and structured for deterministic execution.

```
CapabilityArtifact
├── Metadata (capability_id, version, status: APPROVED | DEGRADED | INVALID)
├── Application Family (vendor: Apex, product: CoreBank, min_version: 4.0.0)
├── Entry Point (route, default_base_url, allowed_domains)
├── Inputs Schema (typed, parameterizable fields, e.g. member_id: string)
├── Outputs Schema (typed, nullable fields, e.g. savings_balance: decimal)
├── Preconditions (route matching, element presence)
├── Steps (ordered actions)
│   ├── Target (scope, frame_context, multi-strategy locator chain, visual fallback)
│   ├── Action (type, click, select, extract)
│   ├── Template (e.g. {{ inputs.member_id }})
│   ├── Risk & Idempotency (risk_level: READ_ONLY | HIGH_RISK, idempotent: bool)
│   ├── Postconditions & Any-Of Branches (Success vs. Business Outcomes)
│   └── Declarative Recovery Rules (TRANSIENT_INTERSTITIAL, max_attempts: 1)
└── Safety Policy (allowed_actions, allowed_routes, requires_confirmation)
```

### Key Design Rationale:
1. **Separation of Intent vs. Mechanism**: The step specifies *what* needs to be typed (`{{ inputs.member_id }}`) and *where* it belongs in the domain, while the target defines an ordered list of locator strategies with confidence scores.
2. **Context & Scoping**: In legacy applications (nested framesets, iframe security dialogs, non-semantic tables), global selectors fail. The schema explicitly supports `scope` (e.g. `form[name='searchForm']`) and `frame_context` (e.g. `dialog_frame`) to isolate locator execution.
3. **Idempotency & Retry Annotations**: Every step declares `idempotent: bool` and `retryable: bool`. Safe read-only steps can automatically mitigate transient loading glitches, whereas irreversible transactions are blocked from blind retries.
4. **Nullable Typed Output Contracts**: In banking, an account may have a checking balance but no savings balance. The schema defines explicit field nullability and transformations (`parse_currency`, `strip`).

---

## 3. Determinism & Error Handling

Deterministic replay in an environment with stable UIs but dynamic runtime conditions requires strict separation between application crashes and legitimate business outcomes.

### The 3-Tier Error Taxonomy

| Tier | Category | Example Scenarios | System Response | Result Contract |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | **Expected Business Outcomes** | Member ID not found, Account frozen, Insufficient funds | Detects expected outcome branch; halts cleanly without crash | `status: BUSINESS_OUTCOME`<br>`outcome_code: MEMBER_NOT_FOUND` |
| **Tier 2** | **Recoverable Conditions** | Maintenance notice interstitial, transient loading spinner | Executes targeted mitigation routine (clicks dismiss) and retries step | `status: SUCCESS`<br>`recovered: true` |
| **Tier 3** | **Hard Failures & Stuck States** | Broken selector, unexpected fatal crash, policy violation | Captures diagnostic evidence (screenshot, DOM snapshot, candidate trace) | `status: HARD_FAILURE`<br>`error: DiagnosticContext` |

### Multi-Strategy Cascading Locators
To defend against subtle DOM shifts, the resolver evaluates locators in descending resilience order:
1. **Accessibility / Semantic Role & Name**: `textbox[name='Member ID / Account #']` (most resilient to markup refactoring).
2. **Scoped Legacy CSS**: `form[name='searchForm'] input.legacy-input[name='memberId']` (isolated within parent container).
3. **Structural XPath**: `.//td[contains(text(),'Member ID')]/following-sibling::td/input` (labels and table relationships).
4. **Visual Coordinates (Fallback)**: Coordinate metadata with explicit viewport scaling used as a last resort.

### Postcondition Branching (`any_of`)
Rather than asserting only a happy-path selector, replay step postconditions define `any_of` branches. For example, submitting a search form simultaneously listens for the success summary table *or* the domain-level error banner. Reaching the error banner immediately resolves as a valid `BUSINESS_OUTCOME` rather than a timeout failure.

---

## 4. Heterogeneity & Multi-Tenant Design

### 1. Surface Abstraction Across Legacy Web & Desktop
To bridge modern browsers, legacy server-rendered framesets, and desktop banking terminals (e.g. AS400, Citrix, Java Swing, WPF):
- The **Capability Artifact** expresses domain intent (e.g. `action: type`, `target: search_field`).
- The **`SurfaceAdapter` Interface** abstracts the physical execution:
  - `PlaywrightSurfaceAdapter`: Translates queries to DOM/CSS/XPath and handles nested `frame_context`.
  - `DesktopSurfaceAdapter` *(Design)*: Connects via Microsoft UI Automation (UIA) or macOS Accessibility APIs, mapping accessibility roles to desktop window handles.
  - `CUASurfaceAdapter` *(Design)*: Maps visual coordinate models and bounding boxes when no accessibility tree exists.

### 2. Multi-Tenant Reuse & Variant Specialization
In banking SaaS, hundreds of institutions run the same vendor software (e.g., *Apex CoreBank v4.x*) configured with different base URLs, custom themes, or slightly modified form fields.

```
[ Base Capability: Apex.CoreBank.get_balance (v1.0.0) ]
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
[ Tenant A Profile ]        [ Tenant B Profile ]
- Base URL: core.banka.com  - Base URL: bankb-core.net
- Custom Header Overrides   - Locator Overrides: #member_num
```

- **Inheritance Model**: A single Base Capability represents the core vendor workflow. Tenant differences are managed as lightweight **Tenant Profiles** containing base URLs and targeted locator overrides.
- **Drift & Health Tracking**: Each run records locator match statistics. If a tenant updates their theme and primary locators fall back to structural XPath, the capability status transitions from `APPROVED` $\to$ `DEGRADED`. If checkpoints fail repeatedly, it becomes `INVALID`, alerting administrators to re-record or adjust the profile without breaking other tenants.

---

## 5. Escalation & Handoff (Human-in-the-Loop)

When automation encounters an ambiguous roadblock, an unexpected security challenge, or an irreversible financial step, it cannot safely guess.

### State Machine & Control Ownership
Control ownership is modeled as an explicit state machine:

```
ControlOwner: [ AUTOMATION ] <=======================> [ HUMAN ]

States:
  RUNNING_AUTOMATION ──(Roadblock / High-Risk Gate)──> AWAITING_HUMAN
  AWAITING_HUMAN     ──(Operator Connects/Acts)──────> HUMAN_CONTROL
  HUMAN_CONTROL      ──(Operator Signals Resume)─────> RESUMING
  RESUMING           ──(Verify Invariants/Postcond)──> RUNNING_AUTOMATION
  AWAITING_HUMAN     ──(Operator Aborts)─────────────> ABORTED
```

### The Same-Session Guarantee
The system maintains the **exact same live browser session** (`session_id` and active `Page` handle):
1. **Seam Trigger**: Replay pauses before executing the high-risk action (`step_authorize_creation`).
2. **Intervention Packaging**: The engine emits `intervention.json` containing `session_id`, `step_index`, `reason`, and a redacted live screenshot.
3. **Live Takeover**: The human operator interacts directly with the active browser window.
4. **Resumption & Audit Trail**: The operator signals completion. The engine logs the operator action into `human_actions.jsonl`, verifies post-action conditions on the live session, transitions `ControlOwner = AUTOMATION`, and deterministically resumes the remaining steps.

---

## 6. Safety & Policy Guardrails

Financial automation systems operate under strict regulatory standards (GLBA, SOC2, PCI-DSS).

### Pre-Action Policy Enforcement
- **Domain/Route Allowlist**: Every destination URL is verified against an allowlist pattern (`^/console/.*$`). Requests to unauthorized or external domains are immediately rejected with a `POLICY_VIOLATION`.
- **Action Verb Allowlist**: Only whitelisted action verbs (`click`, `type`, `select`, `extract`, `scroll`, `wait`) are permitted.
- **Contextual Risk Gate**: Actions targeting irreversible operations (e.g. `Authorize Creation`, `Wire Transfer`) are intercepted before execution and require explicit operator sign-off.

### Regulated Data & PII Protection
- **Textual Data Redaction**: The `PIIRedactor` pipeline scans all logged strings, extracted outputs, and error dumps with regex patterns for Social Security Numbers (`***-**-6789`), Card PANs (`****-****-****-9012`), Passwords, and Authentication Tokens.
- **Screenshot Protection**: Rather than relying on fragile OCR redaction over arbitrary images, the `PlaywrightSurfaceAdapter` injects a DOM-level masking stylesheet (`visibility: hidden` / replacement text on sensitive fields like `#lbl_memberSsn`) *immediately before* invoking `capture_screenshot()`. Furthermore, all demo and test workflows run strictly against synthetic banking fixtures.

---

## 7. Cuts & Next Steps

To deliver a reliable, working end-to-end vertical slice, we prioritized core depth over superficial infrastructure.

### What Was Deliberately Cut:
1. **Distributed Queue Plumbing (Celery / Kafka / Redis)**: Production systems distribute runs across worker pools. We kept execution in-process to ensure deterministic reproducibility and simple single-command setup.
2. **Multi-Tenancy Infrastructure**: We implemented the tenant override schema and drift scoring model, but did not build a multi-tenant database or multi-region routing proxy.
3. **Full WebRTC Operator Streaming Console**: For HITL escalation, we implemented the live session pause/resume seam via headed Playwright browser control and CLI triggers rather than building a custom WebRTC co-browsing web application.

### What We Would Build Next:
1. **Automated Locator Self-Healing**: Utilize historical run telemetry to automatically promote resilient fallback locators to primary priority when UI drift is detected.
2. **Native Desktop Surface Adapter**: Implement a Windows UI Automation (pywinauto/uiautomation) adapter plugging directly into the existing `SurfaceAdapter` protocol.
3. **Continuous Capability Verification**: A cron daemon that periodically executes synthetic replays in staging to detect vendor software updates before production agent invocations occur.
