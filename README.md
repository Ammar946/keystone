# Keystone: Computer-Use Automation System for Banking Back-Office Applications

A production-grade Computer-Use Automation System designed for enterprise banking and credit unions to operate legacy back-office software without APIs.

Built on the two-stage lifecycle:
1. **Discovery (Model in the Loop)**: An LLM-driven agent observes and drives a live application surface, discovers resilient multi-strategy locators, verifies invariants, and compiles the flow into a typed, parameterized **Capability Artifact**.
2. **Deterministic Replay (Zero LLM in Production)**: A pure deterministic execution runtime replayed through a surface-neutral adapter with caller-provided parameters, 3-tier error taxonomy handling, and rich execution telemetry.
3. **Same-Session Human-in-the-Loop (HITL) Escalation**: Pauses automation upon encountering roadblocks or high-risk irreversible actions, cedes control of the **exact same live session** to an operator, captures human intervention, and resumes seamlessly.
4. **Safety & Regulated Data Protection**: Pre-action policy gates, domain allowlists, and strict automated PII/credential redaction across all logs and artifacts.

---

## Repository Structure

```
keystone/
├── app/
│   ├── adapters/
│   │   └── playwright_adapter.py      # Playwright Web & Legacy Frames SurfaceAdapter
│   ├── agent/
│   │   ├── artifact_compiler.py       # Normalizes transcripts into typed Capability Artifacts
│   │   └── discovery_agent.py         # Observe-Decide-Validate-Act discovery engine
│   ├── core/
│   │   ├── error_taxonomy.py          # 3-Tier Error taxonomy & result models
│   │   ├── models.py                  # Pydantic v2 schemas for Capability Artifacts & Steps
│   │   └── surface_adapter.py         # SurfaceAdapter protocol, SurfaceState, & ControlOwner
│   ├── engine/
│   │   ├── checkpoint_engine.py       # Pre/postcondition & any_of branch evaluator
│   │   ├── recovery_handler.py        # Idempotency-aware bounded runtime recovery
│   │   └── replay_engine.py           # Zero-LLM deterministic capability replay engine
│   ├── hitl/
│   │   └── escalation_manager.py      # Same-session live human takeover state machine
│   ├── safety/
│   │   ├── pii_redactor.py            # Automated regex & structured PII/credential masking
│   │   └── policy_gate.py             # Pre-action domain and risk evaluation gate
│   └── target_app/
│       └── server.py                  # "Apex CoreBank Console v4.2" local mock banking portal
├── artifacts/
│   ├── get_member_balance.json        # Compiled member balance query capability artifact
│   └── open_sub_account.json          # Compiled sub-account opening capability artifact
├── evidence/
│   ├── discovery/                     # Discovery logs, actions.jsonl, and screenshots
│   ├── replay-success/                # Deterministic replay logs & extracted outputs
│   ├── replay-business-outcome/       # Expected business outcome (Record Not Found) logs
│   └── replay-hitl/                   # Same-session live intervention & human takeover logs
├── tests/                             # Full automated test suite (24 tests)
├── cli.py                             # Unified CLI entry point
├── REPORT.md                          # 7-Section comprehensive architecture report
└── README.md
```

---

## Quick Start & Setup

### 1. Prerequisites
- Python 3.11+
- Virtual environment (.venv)

### 2. Installation
```bash
# Clone the repository and navigate into the workspace
git clone https://github.com/Ammar946/keystone.git
cd keystone

# Create virtual environment and activate
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt  # Or: pip install fastapi uvicorn jinja2 playwright pydantic pyyaml openai pytest pytest-asyncio rich python-multipart

# Install Playwright browser
playwright install chromium
```

---

## Running the System (Demo Path)

### Step 1: Start the Target Banking Application
In a dedicated terminal, launch the local legacy banking simulation ("Apex CoreBank Console"):
```bash
python cli.py serve-target --port 8080
```
*The portal will be live at `http://localhost:8080/console/members`.*

### Step 2: Run LLM-Driven Discovery
Execute the discovery agent against a natural language goal:
```bash
python cli.py discover --goal "Look up member 10042 and read savings balance"
```
- Observes the live interface, resolves interactive elements, and executes actions.
- Automatically compiles and validates the typed **Capability Artifact**.
- Saves execution evidence to `/evidence/discovery/`.

### Step 3: Run Deterministic Replay (Zero-LLM Production Execution)
Replay the compiled capability artifact with customer parameters without invoking any LLM:
```bash
python cli.py replay --artifact artifacts/get_member_balance.json --inputs '{"member_id":"10042"}'
```
- Replays with cascading locators (Accessibility $\to$ Scoped DOM $\to$ Structural XPath).
- Extracts typed outputs (`savings_balance: 12450.75`, `member_name: Jane Doe`, `account_status: ACTIVE`).
- Saves execution evidence to `/evidence/replay-success/`.

### Step 4: Demonstrate Expected Business Outcome Handling
Replay with a non-existent member ID to demonstrate domain-level outcome branching:
```bash
python cli.py replay-biz --artifact artifacts/get_member_balance.json --inputs '{"member_id":"99999"}'
```
- Classifies result cleanly as `BUSINESS_OUTCOME` with `outcome_code: MEMBER_NOT_FOUND`.
- Returns structured domain feedback to the caller without crashing or reporting hard failure.
- Saves execution evidence to `/evidence/replay-business-outcome/`.

### Step 5: Demonstrate Same-Session Human-in-the-Loop (HITL) Escalation
Run the deposit sub-account creation workflow, which encounters an irreversible security authorization gate:
```bash
# Automated evaluation / CI pipeline mode (simulates operator approval):
python cli.py demo-hitl --auto-approve

# Interactive human operator mode (pauses live browser and waits for operator input):
python cli.py demo-hitl --headed
```
- Automation fills out the form on the live browser page.
- Pre-action safety gate intercepts the high-risk action (`step_authorize_creation`), pauses automation, and yields control (`ControlOwner = HUMAN`).
- Emits `intervention.json` with live screenshot context on `session_id`.
- The operator interacts on the **same live browser page**, authorizes the creation, and signals resume.
- Engine evaluates the postcondition on the live session, automation regains control (`ControlOwner = AUTOMATION`), verifies the provisioned account reference, and saves audit logs in `/evidence/replay-hitl/`.
> **Note on HITL Modes**: `--auto-approve` is provided for deterministic automated demonstration and headless CI pipelines. The production HITL seam supports an actual operator callback controlling the same live browser session.

---

## Running Automated Tests

Run the complete test suite covering schema validation, safety guardrails, PII redaction, deterministic replay, business outcomes, transient recovery, and HITL live takeover:
```bash
source .venv/bin/activate
pytest -v tests/
# Or via CLI:
python cli.py test
```

---

## Architectural Documentation

For an in-depth analysis of system trade-offs, the SurfaceAdapter abstraction, multi-tenant reuse models, error taxonomy, and safety guardrails, see the formal write-up in [REPORT.md].
