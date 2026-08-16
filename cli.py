"""
Unified CLI for Computer-Use Automation System.
Commands:
  - serve-target: Starts the local legacy banking simulation server
  - discover: Runs LLM-driven discovery and produces capability artifact + evidence
  - replay: Runs deterministic replay with typed inputs (zero-LLM)
  - replay-biz: Runs deterministic replay with a non-existent record to demonstrate business outcome handling
  - demo-hitl: Demonstrates same-session live human escalation and handback
  - test: Runs unit and integration test suite
"""
import sys
import os
import json
import asyncio
import argparse
import subprocess
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Ensure current working directory is on pythonpath
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.core.models import CapabilityArtifact
from app.engine.replay_engine import DeterministicReplayEngine
from app.agent.discovery_agent import DiscoveryAgent
from app.adapters.playwright_adapter import PlaywrightSurfaceAdapter
from app.hitl.escalation_manager import HITLEscalationManager
from app.target_app.server import start_server

console = Console()


def run_serve_target(args):
    """Start local mock banking server."""
    console.print(f"[bold green]Starting Apex CoreBank Console v4.2 on http://{args.host}:{args.port}...[/bold green]")
    start_server(host=args.host, port=args.port)


async def run_discovery(args):
    """Execute LLM-driven discovery against a live surface."""
    console.print(Panel(f"[bold cyan]Discovery Agent Goal:[/bold cyan] {args.goal}\n[bold cyan]Target:[/bold cyan] {args.entry_point}", title="Discovery Phase"))
    
    agent = DiscoveryAgent(evidence_dir=args.evidence_dir)
    sample_inputs = json.loads(args.inputs) if args.inputs else {"member_id": "10042"}
    
    with console.status("[bold yellow]Agent exploring live application surface...[/bold yellow]"):
        artifact = await agent.discover_capability(
            goal=args.goal,
            entry_point=args.entry_point,
            sample_inputs=sample_inputs,
            headless=not args.headed,
        )

    console.print(f"\n[bold green]✓ Discovery Completed Successfully![/bold green]")
    console.print(f"Compiled Capability ID: [bold]{artifact.capability_id}[/bold] (v{artifact.version})")
    console.print(f"Artifact saved to: [bold]{args.evidence_dir}/compiled_capability.json[/bold]")
    console.print(f"Run logs and screenshots saved in: [bold]{args.evidence_dir}/[/bold]\n")


async def run_replay(args):
    """Execute deterministic capability replay (Zero LLM)."""
    artifact_path = args.artifact
    if not os.path.exists(artifact_path):
        console.print(f"[bold red]Error: Artifact file '{artifact_path}' not found.[/bold red]")
        sys.exit(1)

    with open(artifact_path, "r") as f:
        artifact_data = json.load(f)
    artifact = CapabilityArtifact.model_validate(artifact_data)

    inputs = json.loads(args.inputs) if args.inputs else {"member_id": "10042"}
    console.print(Panel(
        f"[bold blue]Capability:[/bold blue] {artifact.capability_id} (v{artifact.version})\n"
        f"[bold blue]Inputs:[/bold blue] {inputs}\n"
        f"[bold blue]Zero-LLM Mode:[/bold blue] Active",
        title="Deterministic Replay Execution"
    ))

    engine = DeterministicReplayEngine()
    with console.status("[bold green]Executing deterministic steps against live surface...[/bold green]"):
        result = await engine.replay(
            artifact=artifact,
            inputs=inputs,
            headless=not args.headed,
        )

    # Display Step Trace Table
    trace_table = Table(title="Replay Execution Trace")
    trace_table.add_column("Step ID", style="cyan")
    trace_table.add_column("Action", style="magenta")
    trace_table.add_column("Strategy", style="green")
    trace_table.add_column("Confidence", justify="right")
    trace_table.add_column("Duration", justify="right")
    trace_table.add_column("Status", style="bold")

    for trace in result.step_trace:
        trace_table.add_row(
            trace.step_id,
            trace.action,
            trace.matched_strategy or "-",
            f"{trace.strategy_confidence:.2f}" if trace.strategy_confidence else "-",
            f"{trace.duration_ms:.1f}ms",
            f"[green]{trace.status}[/green]" if trace.status == "SUCCESS" else f"[red]{trace.status}[/red]",
        )
    console.print(trace_table)

    # Save evidence
    os.makedirs(args.evidence_dir, exist_ok=True)
    with open(os.path.join(args.evidence_dir, "run.json"), "w") as f:
        json.dump(result.model_dump(), f, indent=2)
    with open(os.path.join(args.evidence_dir, "result.json"), "w") as f:
        json.dump({"status": result.status.value, "outcome_code": result.outcome_code, "outputs": result.outputs}, f, indent=2)

    # Capture final screenshot if surface is active
    try:
        if engine.surface:
            ss_bytes = await engine.surface.capture_screenshot(mask_sensitive=True)
            if ss_bytes:
                with open(os.path.join(args.evidence_dir, "screenshot_final.png"), "wb") as f:
                    f.write(ss_bytes)
    except Exception:
        pass

    console.print(f"\n[bold]Execution Status:[/bold] {result.status.value}")
    if result.outcome_code:
        console.print(f"[bold yellow]Outcome Code:[/bold yellow] {result.outcome_code}")
    console.print(f"[bold green]Extracted Outputs:[/bold green] {json.dumps(result.outputs, indent=2)}")
    console.print(f"[bold]Total Duration:[/bold] {result.duration_ms:.1f}ms (Steps: {result.steps_executed})\n")


async def run_demo_hitl(args):
    """Demonstrates same-session live human escalation and handback."""
    console.print(Panel(
        "[bold yellow]Scenario:[/bold yellow] Sub-Account Creation flow hits high-risk IRREVERSIBLE authorization step.\n"
        "[bold yellow]Seam:[/bold yellow] System pauses automation, exports intervention context, yields control of the SAME live session to human operator, and resumes.",
        title="Human-in-the-Loop (HITL) Same-Session Live Escalation Demo"
    ))

    # Load open sub-account capability artifact
    with open("artifacts/open_sub_account.json", "r") as f:
        artifact = CapabilityArtifact.model_validate(json.load(f))

    session_id = "sess_hitl_demo_402"
    surface = PlaywrightSurfaceAdapter()
    await surface.initialize(session_id=session_id, entry_point="http://localhost:8080/console/accounts/open", headless=not args.headed)

    escalation_mgr = HITLEscalationManager(surface=surface, evidence_dir=args.evidence_dir)

    try:
        console.print("[cyan][Step 1-3][/cyan] Automation fills form fields on live page...")
        # Step 1: Member ID
        elem1 = await surface.resolve_target(artifact.steps[0].target.model_dump())
        await surface.type_text(elem1, "10042")
        # Step 2: Select Product
        elem2 = await surface.resolve_target(artifact.steps[1].target.model_dump())
        await surface.select_option(elem2, "Money Market")
        # Step 3: Deposit Amount
        elem3 = await surface.resolve_target(artifact.steps[2].target.model_dump())
        await surface.type_text(elem3, "500.00")
        # Step 4: Click Proceed
        elem4 = await surface.resolve_target(artifact.steps[3].target.model_dump())
        await surface.click(elem4)

        console.print("[bold yellow]⚠️  Pre-Action Safety Gate triggered on Step 5: 'step_authorize_creation'[/bold yellow]")
        console.print("Reason: Action involves IRREVERSIBLE core ledger binding. Policy mandates Human-in-the-Loop escalation.")

        # Raise intervention package
        intervention_pkg = await escalation_mgr.raise_intervention_request(
            capability_id=artifact.capability_id,
            step=artifact.steps[4],
            step_index=5,
            reason="High-risk irreversible sub-account ledger creation requires operator confirmation.",
        )
        console.print(f"[bold magenta]Intervention Request Created (Session ID: {session_id}):[/bold magenta]")
        console.print(f"Context saved to: [bold]{args.evidence_dir}/intervention.json[/bold]")
        console.print(f"Current Control Owner: [bold red]{escalation_mgr.control_owner.value}[/bold red]")

        if args.auto_approve:
            console.print("\n[bold green]Operator reviewing live session in background... Approving action.[/bold green]")
            # Simulate human clicking the button inside the iframe modal
            frame_elem = await surface.resolve_target(artifact.steps[4].target.model_dump(), frame_context="dialog_frame")
            await surface.click(frame_elem)
            await escalation_mgr.complete_human_takeover(operator_id="operator_lead_01", action_taken="Confirmed deposit terms and authorized creation", resume_signal=True)
        else:
            console.print("\n[bold cyan]Operator Console Action Required:[/bold cyan]")
            console.print("The live browser session is paused and waiting for human review.")
            input("Press [ENTER] to simulate human operator authorization and resume automation...")
            frame_elem = await surface.resolve_target(artifact.steps[4].target.model_dump(), frame_context="dialog_frame")
            await surface.click(frame_elem)
            await escalation_mgr.complete_human_takeover(operator_id="operator_lead_01", action_taken="Manual operator click on Authorize Creation", resume_signal=True)

        console.print(f"Control returned to: [bold green]{escalation_mgr.control_owner.value}[/bold green]")
        console.print("[cyan][Step 6][/cyan] Automation resumes on the SAME live session to extract confirmed account number...")

        # Step 6: Extract confirmed details
        acc_elem = await surface.resolve_target({"locators": [{"strategy": "xpath_structural", "value": "//strong[@id='lbl_new_account_number']"}]})
        new_acc = await surface.read_text(acc_elem)
        dep_elem = await surface.resolve_target({"locators": [{"strategy": "xpath_structural", "value": "//strong[@id='lbl_confirmed_deposit']"}]})
        dep_val = await surface.read_text(dep_elem)

        final_res = {
            "session_id": session_id,
            "status": "SUCCESS",
            "new_account_number": new_acc,
            "confirmed_deposit": dep_val,
            "human_actions_recorded": len(escalation_mgr.human_actions_log),
        }
        with open(os.path.join(args.evidence_dir, "result.json"), "w") as f:
            json.dump(final_res, f, indent=2)

        with open(os.path.join(args.evidence_dir, "run.json"), "w") as f:
            json.dump({
                "run_id": "run_hitl_001",
                "session_id": session_id,
                "status": "SUCCESS",
                "capability_id": artifact.capability_id,
                "hitl_interventions": 1,
            }, f, indent=2)

        console.print(Panel(
            f"[bold green]✓ Sub-Account Created Successfully on Same Live Session![/bold green]\n"
            f"Allocated Account Number: [bold]{new_acc}[/bold]\n"
            f"Opening Deposit: [bold]{dep_val}[/bold]\n"
            f"Evidence stored at: [bold]{args.evidence_dir}/[/bold]",
            title="HITL Handback Success"
        ))

    finally:
        await surface.close()


def run_tests(args):
    """Run pytest test suite."""
    console.print("[bold green]Running Automated Test Suite...[/bold green]\n")
    res = subprocess.run(["pytest", "-v", "tests/"])
    sys.exit(res.returncode)


def main():
    parser = argparse.ArgumentParser(description="Keystone: Computer-Use Automation System CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # serve-target
    p_serve = subparsers.add_parser("serve-target", help="Start mock legacy banking server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)

    # discover
    p_disc = subparsers.add_parser("discover", help="Run LLM-driven discovery")
    p_disc.add_argument("--goal", default="Look up member 10042 and read savings balance")
    p_disc.add_argument("--entry-point", default="http://localhost:8080/console/members")
    p_disc.add_argument("--inputs", default='{"member_id":"10042"}')
    p_disc.add_argument("--evidence-dir", default="evidence/discovery")
    p_disc.add_argument("--headed", action="store_true")

    # replay
    p_rep = subparsers.add_parser("replay", help="Run deterministic replay (Zero LLM)")
    p_rep.add_argument("--artifact", default="artifacts/get_member_balance.json")
    p_rep.add_argument("--inputs", default='{"member_id":"10042"}')
    p_rep.add_argument("--evidence-dir", default="evidence/replay-success")
    p_rep.add_argument("--headed", action="store_true")

    # replay-biz
    p_biz = subparsers.add_parser("replay-biz", help="Run deterministic replay expecting business outcome (not found)")
    p_biz.add_argument("--artifact", default="artifacts/get_member_balance.json")
    p_biz.add_argument("--inputs", default='{"member_id":"99999"}')
    p_biz.add_argument("--evidence-dir", default="evidence/replay-business-outcome")
    p_biz.add_argument("--headed", action="store_true")

    # demo-hitl
    p_hitl = subparsers.add_parser("demo-hitl", help="Demonstrate same-session HITL escalation and handoff")
    p_hitl.add_argument("--evidence-dir", default="evidence/replay-hitl")
    p_hitl.add_argument("--auto-approve", action="store_true", default=True, help="Auto-approve operator action for automated CI/demo")
    p_hitl.add_argument("--headed", action="store_true")

    # test
    p_test = subparsers.add_parser("test", help="Run automated test suite")

    args = parser.parse_args()

    if args.command == "serve-target":
        run_serve_target(args)
    elif args.command == "discover":
        asyncio.run(run_discovery(args))
    elif args.command == "replay":
        asyncio.run(run_replay(args))
    elif args.command == "replay-biz":
        asyncio.run(run_replay(args))
    elif args.command == "demo-hitl":
        asyncio.run(run_demo_hitl(args))
    elif args.command == "test":
        run_tests(args)


if __name__ == "__main__":
    main()
