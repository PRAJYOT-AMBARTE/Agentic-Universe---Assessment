"""Main Controller Loop: Time Advancement, Event Ingestion, Incident Response, and Optimization."""
from __future__ import annotations

import logging
import time
from typing import Optional

from .analytics import AnalyticsEngine
from .client import SimulatorClient
from .db import Database
from .governance import GovernanceEngine
from .incidents import IncidentManager
from .ingest import EventIngestor
from .optimizer import WorkflowOptimizer

logger = logging.getLogger("controller.loop")


class ControllerLoop:
    """Coordinates the continuous closed-loop autonomous optimization cycle."""

    def __init__(self, client: SimulatorClient, db: Database, tick_step_minutes: int = 60):
        self.client = client
        self.db = db
        self.tick_step = tick_step_minutes

        self.ingestor = EventIngestor(client, db)
        self.analytics = AnalyticsEngine(db)
        self.governance = GovernanceEngine(client, db)
        self.incidents = IncidentManager(client, db, self.analytics, self.governance)
        self.optimizer = WorkflowOptimizer(client, db, self.analytics, self.governance)

    def run(self):
        """Execute the controller loop until the simulation scenario concludes."""
        logger.info("Initializing Controller Loop...")
        health = self.client.get_health()
        logger.info(f"Simulator health check: {health}")

        # Ingest history chunks before D0 if needed
        self.ingestor.ingest_history()

        workflows_cache = {w["workflow_id"]: w for w in self.client.get_workflows()}
        logger.info(f"Loaded {len(workflows_cache)} workflows: {list(workflows_cache.keys())}")

        total_advances = 0
        start_time = time.time()

        while True:
            # 1. Advance simulation
            adv_res = self.client.advance_sim(minutes=self.tick_step)
            total_advances += 1

            sim_minute = adv_res.get("sim_minute", 0)
            sim_day = sim_minute // 1440
            sim_hour = (sim_minute % 1440) // 60
            finished = adv_res.get("finished", False)
            new_chunks = adv_res.get("new_chunks", [])

            # 2. Ingest events
            self.ingestor.ingest_new_chunks(new_chunks)

            # 3. For each workflow: reconcile, respond to incidents, and optimize
            for wid, w_spec in workflows_cache.items():
                # Reconcile pending approvals
                self.governance.reconcile_and_apply(wid, sim_minute)

                # Fetch fresh live config
                cfg_info = self.client.get_config(wid)
                cur_ver = cfg_info["version"]
                cur_cfg = cfg_info["config"]

                # A. Incident Response: Check hallucinations first
                hal_res = self.incidents.handle_hallucination_incidents(
                    workflow_spec=w_spec,
                    current_version=cur_ver,
                    current_config=cur_cfg,
                    sim_minute=sim_minute,
                    sim_hour=sim_hour
                )
                if hal_res and hal_res.get("action") in ("auto_applied", "requested"):
                    continue

                # B. Incident Response: Check caller ID degradation
                did_res = self.incidents.handle_caller_id_degradation(
                    workflow_spec=w_spec,
                    current_version=cur_ver,
                    current_config=cur_cfg,
                    sim_minute=sim_minute,
                    sim_hour=sim_hour
                )
                if did_res and did_res.get("action") in ("auto_applied", "requested"):
                    continue

                # C. Scheduled Optimization: Run at 11:00 and 15:00 during approver hours
                if sim_hour in (11, 15):
                    self.optimizer.optimize_workflow(
                        workflow_spec=w_spec,
                        current_version=cur_ver,
                        current_config=cur_cfg,
                        sim_minute=sim_minute,
                        sim_hour=sim_hour
                    )

            if finished:
                logger.info(f"Scenario completed at sim minute {sim_minute} (elapsed: {time.time() - start_time:.1f}s)")
                break

        final_state = self.client.get_sim_state()
        logger.info(f"Final Simulator State: {final_state}")
