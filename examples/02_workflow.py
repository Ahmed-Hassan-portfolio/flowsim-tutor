"""Example 2 -- tracked workflow with the local SessionManager.

Demonstrates the start_workflow / complete_step / end_session lifecycle.
Sessions persist in ``data/sessions/`` between runs.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from state.session import SessionManager


def main() -> None:
    mgr = SessionManager(PROJECT_ROOT / "data" / "sessions")

    session = mgr.create_session(
        goal="Set up a simple pipeline model",
        phases=[
            {
                "name": "Geometry",
                "description": "Build the pipe table",
                "steps": [
                    {"id": "geo-1", "description": "Import survey", "completed": False},
                    {"id": "geo-2", "description": "Generate pipe table", "completed": False},
                ],
            },
            {
                "name": "Boundary conditions",
                "description": "Define inlet and outlet",
                "steps": [
                    {"id": "bc-1", "description": "Set inlet MASSFLOW", "completed": False},
                    {"id": "bc-2", "description": "Set outlet PRESSURE", "completed": False},
                ],
            },
        ],
    )
    print(f"Created session {session['id'][:8]}")
    print(json.dumps(mgr.get_current(), indent=2, default=str))

    print("\n--- Completing geo-1 ---")
    print(json.dumps(mgr.advance_step("geo-1"), indent=2, default=str))

    print("\n--- Completing geo-2 (advances to next phase) ---")
    print(json.dumps(mgr.advance_step("geo-2"), indent=2, default=str))

    print("\n--- Ending session as abandoned ---")
    print(json.dumps(mgr.end_session(completed=False), indent=2, default=str))


if __name__ == "__main__":
    main()
