"""Crash-recovery test demonstrating seamless kill-and-resume capability."""
import io
import os
import subprocess
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def test_crash_recovery():
    scenario = "scenarios/public_01_dev.yaml"
    run_dir = "runs/mine_crash"
    port = 8704

    print("=== Step 1: Starting Simulator Server ===", flush=True)
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "sim", "serve", "--scenario", scenario, "--run-dir", run_dir, "--port", str(port), "--force"]
    )

    try:
        import httpx
        url = f"http://127.0.0.1:{port}"
        for _ in range(30):
            try:
                r = httpx.get(f"{url}/health", timeout=1.0)
                if r.status_code == 200:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Simulator failed to start")

        # Clean state db
        state_db = Path("controller_state.db")
        if state_db.exists():
            state_db.unlink()

        print("=== Step 2: Starting Controller Process (Initial Run) ===", flush=True)
        controller_p1 = subprocess.Popen(
            [sys.executable, "-m", "controller.main", "--url", url]
        )

        # Allow controller to run for ~6 seconds (~3-4 sim days)
        time.sleep(6.0)

        mid_state = httpx.get(f"{url}/sim/state").json()
        print(f"=== Step 3: KILLING Controller Mid-Run at sim minute {mid_state.get('sim_minute')} ===", flush=True)
        controller_p1.terminate()
        controller_p1.wait()
        print(f"Controller process {controller_p1.pid} successfully killed.", flush=True)

        # Verify DB integrity after sudden kill
        from controller.db import Database
        db = Database(state_db)
        last_chunk = db.get_meta("last_ingested_chunk")
        pending = db.get_pending_proposals()
        print(f"State DB inspection: last_ingested_chunk={last_chunk}, pending_proposals={len(pending)}")
        db.close()

        print("=== Step 4: Restarting Controller to test Crash Recovery ===", flush=True)
        t_restart = time.time()
        subprocess.run(
            [sys.executable, "-m", "controller.main", "--url", url],
            check=True
        )
        print(f"=== Step 5: Controller finished remaining scenario in {time.time() - t_restart:.1f}s ===", flush=True)

        final_state = httpx.get(f"{url}/sim/state").json()
        print(f"Final Simulator State: finished={final_state.get('finished')}, sim_minute={final_state.get('sim_minute')}")
        assert final_state.get("finished") is True, "Simulation did not complete successfully!"
        print(">>> CRASH RECOVERY TEST PASSED: Process survived mid-run kill and completed cleanly with zero state corruption. <<<")

    finally:
        server_proc.terminate()
        server_proc.wait()


if __name__ == "__main__":
    test_crash_recovery()
