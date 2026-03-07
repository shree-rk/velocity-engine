"""
Scheduler
APScheduler-based task scheduling for the Velocity Engine.

Handles:
- Periodic scan cycles (every 3 minutes during market hours)
- Position monitoring
- Equity snapshots
- End-of-day routines
"""

import logging
from datetime import datetime, time, timezone
from typing import Optional, Callable, Dict, Any
from enum import Enum

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import (
    EVENT_JOB_EXECUTED,
    EVENT_JOB_ERROR,
    EVENT_JOB_MISSED,
    JobExecutionEvent
)

from config.settings import SCAN_INTERVAL_MINUTES
from filters.trading_hours import is_regular_hours, check_trading_hours

logger = logging.getLogger(__name__)


class JobType(Enum):
    """Types of scheduled jobs."""
    SCAN = "scan"
    MONITOR = "monitor"
    SNAPSHOT = "snapshot"
    EOD = "end_of_day"
    CUSTOM = "custom"


class VelocityScheduler:
    """
    Scheduler for Velocity Engine automated tasks.
    
    Uses APScheduler BackgroundScheduler for reliable task execution.
    """
    
    def __init__(
        self,
        scan_callback: Callable = None,
        monitor_callback: Callable = None,
        snapshot_callback: Callable = None,
        eod_callback: Callable = None,
        scan_interval_minutes: int = None,
        market_hours_only: bool = True
    ):
        """
        Initialize scheduler.
        
        Args:
            scan_callback: Function to call for scans.
            monitor_callback: Function to call for position monitoring.
            snapshot_callback: Function to call for equity snapshots.
            eod_callback: Function to call at end of day.
            scan_interval_minutes: Minutes between scans (default from config).
            market_hours_only: Only run during market hours.
        """
        self.scan_callback = scan_callback
        self.monitor_callback = monitor_callback
        self.snapshot_callback = snapshot_callback
        self.eod_callback = eod_callback
        
        self.scan_interval = scan_interval_minutes or SCAN_INTERVAL_MINUTES
        self.market_hours_only = market_hours_only
        
        # Initialize scheduler
        self._scheduler = BackgroundScheduler(
            timezone='America/New_York',
            job_defaults={
                'coalesce': True,  # Combine missed jobs
                'max_instances': 1,  # Prevent overlap
                'misfire_grace_time': 60  # Allow 60s delay
            }
        )
        
        # Job tracking
        self._jobs: Dict[str, Any] = {}
        self._is_running = False
        
        # Statistics
        self._stats = {
            "scans_executed": 0,
            "scans_skipped": 0,
            "monitors_executed": 0,
            "errors": 0,
            "last_scan": None,
            "last_error": None
        }
        
        # Add event listeners
        self._scheduler.add_listener(
            self._on_job_executed,
            EVENT_JOB_EXECUTED
        )
        self._scheduler.add_listener(
            self._on_job_error,
            EVENT_JOB_ERROR
        )
        self._scheduler.add_listener(
            self._on_job_missed,
            EVENT_JOB_MISSED
        )
        
        logger.info(
            f"Scheduler initialized - Scan interval: {self.scan_interval}min, "
            f"Market hours only: {self.market_hours_only}"
        )
    
    # =========================================================================
    # Lifecycle
    # =========================================================================
    
    def start(self) -> None:
        """Start the scheduler."""
        if self._is_running:
            logger.warning("Scheduler already running")
            return
        
        logger.info("Starting scheduler...")
        
        # Add default jobs
        self._setup_default_jobs()
        
        # Start scheduler
        self._scheduler.start()
        self._is_running = True
        
        logger.info("✓ Scheduler started")
    
    def stop(self) -> None:
        """Stop the scheduler."""
        if not self._is_running:
            return
        
        logger.info("Stopping scheduler...")
        
        self._scheduler.shutdown(wait=True)
        self._is_running = False
        
        logger.info("✓ Scheduler stopped")
    
    def pause(self) -> None:
        """Pause all jobs."""
        self._scheduler.pause()
        logger.info("Scheduler paused")
    
    def resume(self) -> None:
        """Resume all jobs."""
        self._scheduler.resume()
        logger.info("Scheduler resumed")
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._is_running
    
    # =========================================================================
    # Job Setup
    # =========================================================================
    
    def _setup_default_jobs(self) -> None:
        """Set up default scheduled jobs."""
        
        # Scan job - every N minutes during market hours
        if self.scan_callback:
            self.add_scan_job()
        
        # Monitor job - every minute during market hours
        if self.monitor_callback:
            self.add_monitor_job()
        
        # Equity snapshot - every 15 minutes during market hours
        if self.snapshot_callback:
            self.add_snapshot_job()
        
        # End of day job - at market close
        if self.eod_callback:
            self.add_eod_job()
    
    def add_scan_job(
        self,
        interval_minutes: int = None,
        job_id: str = "scan_main"
    ) -> None:
        """
        Add scan job.
        
        Args:
            interval_minutes: Scan interval (default from config).
            job_id: Unique job identifier.
        """
        interval = interval_minutes or self.scan_interval
        
        # Wrapper to check market hours
        def scan_wrapper():
            if self.market_hours_only and not is_regular_hours():
                self._stats["scans_skipped"] += 1
                logger.debug("Scan skipped - outside market hours")
                return
            
            if self.scan_callback:
                self.scan_callback()
                self._stats["scans_executed"] += 1
                self._stats["last_scan"] = datetime.now(timezone.utc)
        
        job = self._scheduler.add_job(
            scan_wrapper,
            trigger=IntervalTrigger(minutes=interval),
            id=job_id,
            name="Strategy Scan",
            replace_existing=True
        )
        
        self._jobs[job_id] = job
        logger.info(f"Scan job added: every {interval} minutes")
    
    def add_monitor_job(
        self,
        interval_seconds: int = 60,
        job_id: str = "monitor_positions"
    ) -> None:
        """
        Add position monitoring job.
        
        Args:
            interval_seconds: Monitor interval.
            job_id: Unique job identifier.
        """
        def monitor_wrapper():
            if self.market_hours_only and not is_regular_hours():
                return
            
            if self.monitor_callback:
                self.monitor_callback()
                self._stats["monitors_executed"] += 1
        
        job = self._scheduler.add_job(
            monitor_wrapper,
            trigger=IntervalTrigger(seconds=interval_seconds),
            id=job_id,
            name="Position Monitor",
            replace_existing=True
        )
        
        self._jobs[job_id] = job
        logger.info(f"Monitor job added: every {interval_seconds}s")
    
    def add_snapshot_job(
        self,
        interval_minutes: int = 15,
        job_id: str = "equity_snapshot"
    ) -> None:
        """
        Add equity snapshot job.
        
        Args:
            interval_minutes: Snapshot interval.
            job_id: Unique job identifier.
        """
        def snapshot_wrapper():
            if self.market_hours_only and not is_regular_hours():
                return
            
            if self.snapshot_callback:
                self.snapshot_callback()
        
        job = self._scheduler.add_job(
            snapshot_wrapper,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id=job_id,
            name="Equity Snapshot",
            replace_existing=True
        )
        
        self._jobs[job_id] = job
        logger.info(f"Snapshot job added: every {interval_minutes}min")
    
    def add_eod_job(
        self,
        hour: int = 16,
        minute: int = 5,
        job_id: str = "end_of_day"
    ) -> None:
        """
        Add end-of-day job.
        
        Args:
            hour: Hour to run (24h format, ET).
            minute: Minute to run.
            job_id: Unique job identifier.
        """
        job = self._scheduler.add_job(
            self.eod_callback,
            trigger=CronTrigger(
                hour=hour,
                minute=minute,
                day_of_week='mon-fri',
                timezone='America/New_York'
            ),
            id=job_id,
            name="End of Day",
            replace_existing=True
        )
        
        self._jobs[job_id] = job
        logger.info(f"EOD job added: {hour}:{minute:02d} ET weekdays")
    
    def add_custom_job(
        self,
        callback: Callable,
        job_id: str,
        trigger: Any,
        name: str = None
    ) -> None:
        """
        Add a custom scheduled job.
        
        Args:
            callback: Function to call.
            job_id: Unique job identifier.
            trigger: APScheduler trigger.
            name: Job name.
        """
        job = self._scheduler.add_job(
            callback,
            trigger=trigger,
            id=job_id,
            name=name or job_id,
            replace_existing=True
        )
        
        self._jobs[job_id] = job
        logger.info(f"Custom job added: {job_id}")
    
    # =========================================================================
    # Job Management
    # =========================================================================
    
    def remove_job(self, job_id: str) -> bool:
        """
        Remove a scheduled job.
        
        Args:
            job_id: Job identifier.
            
        Returns:
            True if removed.
        """
        try:
            self._scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            logger.info(f"Job removed: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove job {job_id}: {e}")
            return False
    
    def pause_job(self, job_id: str) -> bool:
        """Pause a specific job."""
        try:
            self._scheduler.pause_job(job_id)
            logger.info(f"Job paused: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to pause job {job_id}: {e}")
            return False
    
    def resume_job(self, job_id: str) -> bool:
        """Resume a specific job."""
        try:
            self._scheduler.resume_job(job_id)
            logger.info(f"Job resumed: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to resume job {job_id}: {e}")
            return False
    
    def run_job_now(self, job_id: str) -> bool:
        """
        Trigger a job to run immediately.
        
        Args:
            job_id: Job identifier.
            
        Returns:
            True if triggered.
        """
        if job_id not in self._jobs:
            logger.warning(f"Job not found: {job_id}")
            return False
        
        try:
            job = self._scheduler.get_job(job_id)
            if job:
                job.modify(next_run_time=datetime.now())
                logger.info(f"Job triggered: {job_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to trigger job {job_id}: {e}")
        
        return False
    
    # =========================================================================
    # Event Handlers
    # =========================================================================
    
    def _on_job_executed(self, event: JobExecutionEvent) -> None:
        """Handle job execution event."""
        logger.debug(f"Job executed: {event.job_id}")
    
    def _on_job_error(self, event: JobExecutionEvent) -> None:
        """Handle job error event."""
        self._stats["errors"] += 1
        self._stats["last_error"] = {
            "job_id": event.job_id,
            "time": datetime.now(timezone.utc),
            "exception": str(event.exception)
        }
        
        logger.error(
            f"Job error: {event.job_id} - {event.exception}"
        )
    
    def _on_job_missed(self, event: JobExecutionEvent) -> None:
        """Handle job missed event."""
        logger.warning(f"Job missed: {event.job_id}")
    
    # =========================================================================
    # Status & Stats
    # =========================================================================
    
    def get_jobs(self) -> Dict[str, Dict]:
        """
        Get all scheduled jobs.
        
        Returns:
            Dictionary of job info.
        """
        jobs = {}
        
        for job in self._scheduler.get_jobs():
            jobs[job.id] = {
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
                "pending": job.pending
            }
        
        return jobs
    
    def get_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        return {
            "is_running": self._is_running,
            "job_count": len(self._jobs),
            **self._stats
        }
    
    def get_next_scan_time(self) -> Optional[datetime]:
        """Get next scheduled scan time."""
        job = self._scheduler.get_job("scan_main")
        if job and job.next_run_time:
            return job.next_run_time
        return None


# ============================================================================
# Factory Function
# ============================================================================

def create_scheduler(
    engine,
    scan_interval: int = None
) -> VelocityScheduler:
    """
    Create a scheduler connected to an engine.
    
    Args:
        engine: VelocityEngine instance.
        scan_interval: Scan interval in minutes.
        
    Returns:
        Configured VelocityScheduler.
    """
    return VelocityScheduler(
        scan_callback=engine.run_scan,
        monitor_callback=engine.monitor_positions,
        snapshot_callback=None,  # TODO: Add snapshot to engine
        eod_callback=None,  # TODO: Add EOD to engine
        scan_interval_minutes=scan_interval
    )
