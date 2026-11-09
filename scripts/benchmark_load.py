"""Benchmark script to measure load performance on public_03_load."""
import io
import os
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def run_load_benchmark():
    scenario = "scenarios/public_03_load.yaml"
    run_dir = "runs/mine03"
    port = 8703

    print(f"=== Starting simulator for {scenario} on port {port} (history generation may take ~2 min) ===", flush=True)
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "sim", "serve", "--scenario", scenario, "--run-dir", run_dir, "--port", str(port), "--force"]
    )

    try:
        import httpx
        url = f"http://127.0.0.1:{port}"
        # Give up to 300 seconds for 1.5GB history generation
        for i in range(300):
            try:
                r = httpx.get(f"{url}/health", timeout=1.0)
                if r.status_code == 200:
                    print(f"Simulator ready after {i}s", flush=True)
                    break
            except Exception:
                time.sleep(1.0)
        else:
            raise RuntimeError("Simulator failed to start within 300 seconds")

        state_db = Path("controller_state.db")
        if state_db.exists():
            state_db.unlink()

        print(f"=== Running controller load test against {url} ===", flush=True)
        t0 = time.time()
        
        proc = subprocess.run(
            [sys.executable, "-m", "controller.main", "--url", url],
            check=True
        )
        elapsed = time.time() - t0

        st = httpx.get(f"{url}/sim/state").json()
        print(f"Finished in {elapsed:.2f}s wall-clock time!")
        print(f"Sim state: {st}")
        print(f"Wall-clock time per simulated day: {elapsed / 5:.2f}s (SRE Budget: < 600s)")

    finally:
        server_proc.terminate()
        server_proc.wait()


if __name__ == "__main__":
    run_load_benchmark()
