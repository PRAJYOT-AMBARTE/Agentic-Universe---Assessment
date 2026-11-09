"""CLI script to query audit explanation from the controller audit store."""
import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controller.db import Database


def main():
    parser = argparse.ArgumentParser(description="Query audit history for a workflow")
    parser.add_argument("--db", default="controller_state.db", help="Path to controller state db")
    parser.add_argument("--workflow", default=None, help="Filter by workflow id")
    parser.add_argument("--limit", type=int, default=10, help="Number of records to show")
    args = parser.parse_args()

    db = Database(args.db)
    logs = db.query_audit_log(workflow_id=args.workflow, limit=args.limit)

    print(f"=== Audit Trail for workflow: {args.workflow or 'ALL'} (showing latest {len(logs)}) ===")
    for entry in logs:
        print(f"[{entry['ts']}] ({entry['actor']}) {entry['event_type'].upper()}: {entry['summary']}")
        if entry["details"]:
            try:
                dt = json.loads(entry["details"])
                print(f"    Details: {json.dumps(dt, indent=2)}")
            except Exception:
                print(f"    Details: {entry['details']}")
        print("-" * 60)
    db.close()


if __name__ == "__main__":
    main()
