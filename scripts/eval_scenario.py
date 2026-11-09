"""Helper script to run a scenario end-to-end with the simulator and controller."""
import argparse
import io
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def run_scenario(scenario_path: str, run_dir: str, baseline_dir: str, report_path: str, port: int = 8700):
    run_path = Path(run_dir)
    base_path = Path(baseline_dir)
    rep_path = Path(report_path)
    rep_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Run baseline if not already present
    if not base_path.exists() or not any(base_path.iterdir()):
        print(f"=== Generating baseline in {baseline_dir} ===", flush=True)
        subprocess.run([sys.executable, "-m", "sim", "baseline", "--scenario", scenario_path, "--run-dir", baseline_dir], check=True)

    # 2. Start simulator server
    print(f"=== Starting simulator server on port {port} (run_dir: {run_dir}) ===", flush=True)
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "sim", "serve", "--scenario", scenario_path, "--run-dir", run_dir, "--port", str(port), "--force"]
    )

    try:
        # Wait for server to become healthy
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
            raise RuntimeError("Simulator failed to start within 15 seconds")

        # 3. Run controller
        print(f"=== Running controller against {url} ===", flush=True)
        # Delete old state db if present so it's a fresh run
        state_db = Path("controller_state.db")
        if state_db.exists():
            state_db.unlink()

        t0 = time.time()
        subprocess.run(
            [sys.executable, "-m", "controller.main", "--url", url],
            check=True
        )
        print(f"Controller finished in {time.time() - t0:.1f}s", flush=True)

    finally:
        server_proc.terminate()
        server_proc.wait()

    # 4. Grade run
    print(f"=== Grading run vs baseline -> {report_path} ===", flush=True)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "sim", "grade", "--run", run_dir, "--baseline", baseline_dir, "--out", str(rep_path)],
        env=env,
        check=True
    )
    print(f"Report written to {report_path}")
    print(rep_path.read_text(encoding="utf-8", errors="replace"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--baseline-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--port", type=int, default=8700)
    args = parser.parse_args()

    run_scenario(args.scenario, args.run_dir, args.baseline_dir, args.report, args.port)
