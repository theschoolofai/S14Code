"""Part 2 proof: ResuMake AI Resume Builder answers ONLY in composed interfaces across 8 turns + final A4 Bento summary.

Drives the real gateway across 8 turns matching 1-Page A4 Bento Box specification where every response is a composed, catalog-validated A2UI surface.

Run against active S14Code service:
    S14_BASE=http://127.0.0.1:8113 uv run python proofs/resume_conversation.py
      -> proofs/resume_conversation.json
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

BASE = os.getenv("S14_BASE", "http://127.0.0.1:8113").rstrip("/")
OUT = Path(__file__).parent / "resume_conversation.json"

OPENING = "Turn 1: Identity & Target Role (Alex Rivera, Senior AI Systems Engineer)"

TAPS = [
    "Turn 2: Contact Information & Links",
    "Turn 3: Seniority & Bio",
    "Turn 4: Work Experience & AI Bullet Enhancer",
    "Turn 5: Education & Credentials",
    "Turn 6: Select Skills & Star Ratings",
    "Turn 7: Career Impact Stats",
    "Turn 8: Bento Resume Theme Selection",
    "FINAL: Generate 1-Page A4 Bento Resume",
]


def goal_for(convo: list[str]) -> str:
    len_convo = len(convo)
    last = convo[-1]
    
    if len_convo == 1 or "Turn 1" in last or "Identity" in last:
        return (
            "The user is starting the AI Resume Builder. " +
            "This is TURN 1 of 8 (Identity & Target Role). " +
            "CRITICAL: DO NOT GENERATE THE FINAL COMPLETED RESUME YET! " +
            "Compose TURN 1 interface: " +
            "1. StepWizard component with steps ['1. Identity', '2. Contact', '3. Bio', '4. Experience', '5. Education', '6. Skills', '7. Stats', '8. Style', 'Final A4 Resume'], currentStep 1. " +
            "2. Text heading 'Step 1: Identity & Target Role'. " +
            "3. TextField for 'Full Name' (placeholder e.g. Alex Rivera). " +
            "4. TextField for 'Target Job Title' (placeholder e.g. Senior AI Systems Engineer). " +
            "5. InputChoice for 'Industry Domain' with options ['AI & Robotics', 'Software Engineering', 'Design', 'Marketing', 'Product', 'Other']. " +
            "6. Button labeled 'Continue to Step 2: Contact Info' with onPress action 'approve'."
        )

    if "Turn 2" in last or "Contact" in last or len_convo == 2:
        return (
            "The user entered identity info: \"" + last + "\". " +
            "This is TURN 2 of 8 (Contact Information & Social Links). " +
            "CRITICAL: DO NOT GENERATE THE FINAL RESUME YET! " +
            "Compose TURN 2 interface: " +
            "1. StepWizard with currentStep 2. " +
            "2. Text heading 'Step 2: Contact Information & Links'. " +
            "3. TextField for 'Email Address', 'Phone Number', 'Location', 'LinkedIn / Portfolio Link'. " +
            "4. Button labeled 'Continue to Step 3: Seniority & Bio' with onPress action 'approve'."
        )

    if "Turn 3" in last or "Bio" in last or len_convo == 3:
        return (
            "The user entered contact details: \"" + last + "\". " +
            "This is TURN 3 of 8 (Seniority & Executive Bio). " +
            "CRITICAL: DO NOT GENERATE THE FINAL RESUME YET! " +
            "Compose TURN 3 interface: " +
            "1. StepWizard with currentStep 3. " +
            "2. Text heading 'Step 3: Seniority & Elevator Pitch'. " +
            "3. InputChoice for Experience Level with options ['Fresher', '1-3 years', '3-7 years', '7+ years']. " +
            "4. TextField for 'Executive Bio / Elevator Pitch'. " +
            "5. Button labeled 'Continue to Step 4: Work Experience' with onPress action 'approve'."
        )

    if "Turn 4" in last or "Work Experience" in last or len_convo == 4:
        return (
            "The user entered bio & seniority: \"" + last + "\". " +
            "This is TURN 4 of 8 (Work Experience & AI Bullet Enhancer). " +
            "CRITICAL: DO NOT GENERATE THE FINAL RESUME YET! " +
            "Compose TURN 4 interface: " +
            "1. StepWizard with currentStep 4. " +
            "2. Text heading 'Step 4: Work Experience & Achievement Enhancer'. " +
            "3. TextField for 'Company Name & Position', 'Dates Worked', 'Draft Achievement Bullet Point'. " +
            "4. CodeDiff component showing AI Bullet Enhancer (Draft vs AI STAR method bullet). " +
            "5. Button labeled 'Continue to Step 5: Education' with onPress action 'approve'."
        )

    if "Turn 5" in last or "Education" in last or len_convo == 5:
        return (
            "The user entered work experience: \"" + last + "\". " +
            "This is TURN 5 of 8 (Education Entry). " +
            "CRITICAL: DO NOT GENERATE THE FINAL RESUME YET! " +
            "Compose TURN 5 interface: " +
            "1. StepWizard with currentStep 5. " +
            "2. Text heading 'Step 5: Education & Credentials'. " +
            "3. TextField for 'University / School', 'Degree & Major', 'Graduation Year & Honors'. " +
            "4. Button labeled 'Continue to Step 6: Skills' with onPress action 'approve'."
        )

    if "Turn 6" in last or "Skills" in last or len_convo == 6:
        return (
            "The user entered education: \"" + last + "\". " +
            "This is TURN 6 of 8 (Core Skills & Star Ratings). " +
            "CRITICAL: DO NOT GENERATE THE FINAL RESUME YET! " +
            "Compose TURN 6 interface: " +
            "1. StepWizard with currentStep 6. " +
            "2. Text heading 'Step 6: Core Skills & Proficiency Ratings'. " +
            "3. Rating components for top technical skills (5-star ratings). " +
            "4. InputChoice for Additional Skill Tags. " +
            "5. Button labeled 'Continue to Step 7: Impact Stats' with onPress action 'approve'."
        )

    if "Turn 7" in last or "Stats" in last or len_convo == 7:
        return (
            "The user entered skills: \"" + last + "\". " +
            "This is TURN 7 of 8 (Career Impact Stats). " +
            "CRITICAL: DO NOT GENERATE THE FINAL RESUME YET! " +
            "Compose TURN 7 interface: " +
            "1. StepWizard with currentStep 7. " +
            "2. Text heading 'Step 7: Key Impact Highlights'. " +
            "3. StatTile components for metric highlights (+65% Throughput, $1.2M Saved, 8+ Yrs Exp). " +
            "4. Button labeled 'Continue to Step 8: Bento Theme' with onPress action 'approve'."
        )

    if "Turn 8" in last or "Style" in last or "Theme" in last or len_convo == 8:
        return (
            "The user entered impact stats: \"" + last + "\". " +
            "This is TURN 8 of 8 (Bento Resume Theme Selection). " +
            "CRITICAL: DO NOT GENERATE THE FINAL RESUME YET! " +
            "Compose TURN 8 interface: " +
            "1. StepWizard with currentStep 8. " +
            "2. Text heading 'Step 8: Choose Bento Grid Theme'. " +
            "3. InputChoice for Theme with options ['Dark Glassmorphism Bento', 'Modern Executive Light', 'Minimal Slate', 'Cyber Neon']. " +
            "4. Button labeled 'Generate 1-Page A4 Bento Resume' with onPress action 'approve'."
        )

    return (
        "The user completed all 8 turns. " +
        "This is the FINAL TURN 9 (1-PAGE A4 BENTO BOX RESUME COMPONENT). " +
        "Compose a complete, live, pixel-perfect 1-Page A4 Bento Grid Resume preview using all collected data: " +
        "1. StepWizard component with currentStep 9 (Complete). " +
        "2. Header Bento Box with Candidate Name, Job Title, Contact Badges, and Social Links. " +
        "3. Bio Bento Card with Elevator Pitch. " +
        "4. StatTile Bento Row with 3 Career Highlight Metrics. " +
        "5. Work Experience Bento Box with AI-enhanced STAR bullets. " +
        "6. Education Bento Box. " +
        "7. Rating Grid Bento Box for Skills. " +
        "8. ApprovalCard labeled 'Bento Resume Complete' with 'Approve & Print/Export A4 PDF' action."
    )


def turn(client: httpx.Client, convo: list[str]) -> dict:
    started = time.time()
    run = client.post(f"{BASE}/v1/agent/runs", json={
        "tenant_id": "course",
        "project_id": "s14-resume",
        "user_id": "jobseeker-synthetic-01",
        "agent_id": "resumake",
        "respond_as": "ui",
        "prompt": goal_for(convo),
    }).json()
    run_id = run["run_id"]
    res_comp = None
    for attempt in range(6):
        res_comp = client.get(f"{BASE}/v1/runs/{run_id}/composed")
        if res_comp.status_code == 200:
            break
        if attempt < 5:
            time.sleep(2)
        else:
            print(f"[{convo[-1]}] Server error {res_comp.status_code} after retries: {res_comp.text}")
            res_comp.raise_for_status()
    composed = res_comp.json()
    journal = client.get(f"{BASE}/v1/agent/runs/{run_id}").json()
    validator = ((journal.get("nodes", {}).get("surface") or {}).get("result") or {}).get("validator") or {}
    surface = composed["surface"]
    types = sorted({c["type"] for c in surface["components"]})
    return {
        "user_said": convo[-1],
        "goal_sent": goal_for(convo),
        "run_id": run_id,
        "latency_s": round(time.time() - started, 1),
        "provider": composed.get("provider"),
        "model": composed.get("model"),
        "clean": composed.get("clean"),
        "component_count": composed.get("component_count"),
        "component_types": types,
        "validator": validator,
        "data_pointers": sorted(surface.get("dataModel", {}).keys()),
        "surface": surface,
    }


def main() -> None:
    convo: list[str] = [OPENING]
    turns = []
    with httpx.Client(timeout=300) as client:
        for index in range(len(TAPS) + 1):
            if index:
                convo.append(TAPS[index - 1])
            record = turn(client, convo)
            turns.append(record)
            unresolved = (record["validator"] or {}).get("unresolved_bindings") or []
            print(f"turn {index + 1}: {record['component_count']:>2} components, "
                  f"clean={record['clean']}, {record['latency_s']}s  {record['component_types']}"
                  + (f"  !! bound to nothing: {unresolved}" if unresolved else ""))

    signatures = [tuple(t["component_types"]) for t in turns]
    union = {t for sig in signatures for t in sig}
    coverage = {
        "step wizard -> StepWizard": sorted(union & {"StepWizard"}),
        "single/multi select -> InputChoice/CheckBox": sorted(union & {"InputChoice", "CheckBox"}),
        "identity & text fields -> TextField": sorted(union & {"TextField"}),
        "bullet enhancer -> CodeDiff": sorted(union & {"CodeDiff"}),
        "skill ratings -> Rating": sorted(union & {"Rating"}),
        "final Bento A4 resume -> Card/DataTable/ApprovalCard": sorted(union & {"Card", "DataTable", "ApprovalCard"}),
    }
    report = {
        "base": BASE,
        "turns": turns,
        "every_turn_composed": all(t["component_count"] > 0 for t in turns),
        "every_turn_clean": all(t["clean"] for t in turns),
        "distinct_component_signatures": len(set(signatures)),
        "union_of_component_types": sorted(union),
        "rich_component_coverage": coverage,
        "every_shape_got_its_component": all(bool(v) for v in coverage.values()),
        "every_binding_resolved": all(
            not ((t["validator"] or {}).get("unresolved_bindings") or []) for t in turns),
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\ndistinct interface shapes: {report['distinct_component_signatures']}/{len(turns)}")
    print(f"components used across conversation: {report['union_of_component_types']}")
    for shape, hit in coverage.items():
        print(f"  {shape:36} {hit if hit else '** ABSENT **'}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
