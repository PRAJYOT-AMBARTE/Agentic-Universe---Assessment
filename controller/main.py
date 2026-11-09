"""CLI Entry Point for the Outcome-First Agent Loop Controller."""
import argparse
import logging
import sys

from controller.client import SimulatorClient
from controller.db import Database
from controller.loop import ControllerLoop


def main():
    parser = argparse.ArgumentParser(description="Autonomous Outcome-First Agent Loop Controller")
    parser.add_argument("--url", default="http://127.0.0.1:8700", help="Simulator API base URL")
    parser.add_argument("--db", default="controller_state.db", help="SQLite database path")
    parser.add_argument("--step", type=int, default=60, help="Advance simulation step in minutes (default 60)")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )

    client = SimulatorClient(base_url=args.url)
    db = Database(db_path=args.db)

    try:
        loop = ControllerLoop(client=client, db=db, tick_step_minutes=args.step)
        loop.run()
    except KeyboardInterrupt:
        logging.info("Controller interrupted by user.")
        sys.exit(0)
    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    main()
