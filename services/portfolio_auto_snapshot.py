"""Scheduled portfolio NAV snapshot worker."""

from __future__ import annotations

import threading
import traceback
from datetime import date, datetime, timedelta
from typing import Callable, Optional


class PortfolioAutoSnapshotScheduler:
    """Run one portfolio snapshot after the configured daily close time.

    The scheduler deliberately keeps the scheduling concern separate from the
    portfolio calculation and persistence code. ``snapshot_callback`` owns
    the quote-date check and the actual database write, while this class only
    decides when to call it and retries short-lived quote failures.
    """

    def __init__(
        self,
        snapshot_callback: Callable[[date], dict],
        *,
        enabled: bool = True,
        hour: int = 15,
        minute: int = 5,
        retry_count: int = 3,
        retry_seconds: int = 60,
        log_path: Optional[str] = None,
        now_func: Optional[Callable[[], datetime]] = None,
    ):
        self.snapshot_callback = snapshot_callback
        self.enabled = bool(enabled)
        self.hour = max(0, min(23, int(hour)))
        self.minute = max(0, min(59, int(minute)))
        self.retry_count = max(1, int(retry_count))
        self.retry_seconds = max(1, int(retry_seconds))
        self.log_path = log_path
        self.now_func = now_func or datetime.now
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._running = False
        self._next_run_at = None
        self._last_run_date = None
        self._last_result = {
            "status": "idle",
            "message": "尚未执行自动净值记录",
            "updated_at": None,
        }

    def start(self):
        if not self.enabled:
            self._set_result("disabled", "自动净值记录已关闭")
            return False
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="portfolio-auto-snapshot",
                daemon=True,
            )
            self._thread.start()
        self._write_log(
            f"started schedule={self.hour:02d}:{self.minute:02d} "
            f"retry_count={self.retry_count} retry_seconds={self.retry_seconds}"
        )
        return True

    def stop(self, timeout=5):
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0, float(timeout)))

    def run_once(self, snapshot_date=None, reason="manual"):
        """Execute one run synchronously; useful for diagnostics and tests."""
        target_date = snapshot_date or self.now_func().date()
        return self._run_for_date(target_date, reason)

    def status(self):
        with self._lock:
            thread = self._thread
            return {
                "enabled": self.enabled,
                "running": bool(self._running),
                "thread_alive": bool(thread and thread.is_alive()),
                "schedule": f"{self.hour:02d}:{self.minute:02d}",
                "retry_count": self.retry_count,
                "retry_seconds": self.retry_seconds,
                "next_run_at": self._next_run_at.isoformat(timespec="seconds") if self._next_run_at else None,
                "last_run_date": self._last_run_date.isoformat() if self._last_run_date else None,
                "last_result": dict(self._last_result),
            }

    def _run_loop(self):
        now = self.now_func()
        today_target = self._target_at(now.date())
        if now >= today_target and today_target.weekday() < 5:
            self._run_for_date(now.date(), "startup")

        while not self._stop_event.is_set():
            now = self.now_func()
            next_run = self._next_target(now)
            with self._lock:
                self._next_run_at = next_run
            wait_seconds = max(0.5, (next_run - now).total_seconds())
            if self._stop_event.wait(min(wait_seconds, 60)):
                return
            if self.now_func() >= next_run:
                self._run_for_date(next_run.date(), "scheduled")

    def _run_for_date(self, target_date, reason):
        if target_date.weekday() >= 5:
            result = {
                "status": "skipped",
                "message": "周末不记录净值",
                "date": target_date.isoformat(),
                "reason": reason,
            }
            self._set_result(result["status"], result["message"], result)
            return result

        with self._lock:
            self._running = True
        last_result = None
        try:
            for attempt in range(1, self.retry_count + 1):
                try:
                    result = self.snapshot_callback(target_date) or {}
                except Exception as exc:
                    result = {
                        "status": "failed",
                        "message": str(exc),
                        "error": traceback.format_exc(),
                    }
                result = {
                    **result,
                    "date": result.get("date") or target_date.isoformat(),
                    "reason": reason,
                    "attempt": attempt,
                }
                last_result = result
                if result.get("status") == "saved":
                    self._set_result("saved", result.get("message") or "自动净值已记录", result)
                    self._write_log(
                        f"saved date={target_date.isoformat()} "
                        f"attempt={attempt} message={result.get('message', '')}"
                    )
                    return result

                self._set_result(
                    result.get("status") or "waiting",
                    result.get("message") or "等待有效收盘行情",
                    result,
                )
                self._write_log(
                    f"retry date={target_date.isoformat()} attempt={attempt} "
                    f"status={result.get('status')} message={result.get('message', '')}"
                )
                if attempt < self.retry_count and not self._stop_event.wait(self.retry_seconds):
                    continue
                break
            return last_result or {
                "status": "skipped",
                "message": "没有可用的自动净值数据",
                "date": target_date.isoformat(),
                "reason": reason,
            }
        finally:
            with self._lock:
                self._running = False
                self._last_run_date = target_date

    def _target_at(self, target_date):
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            self.hour,
            self.minute,
        )

    def _next_target(self, now):
        target = self._target_at(now.date())
        if now >= target:
            target += timedelta(days=1)
        while target.weekday() >= 5:
            target += timedelta(days=1)
        return target

    def _set_result(self, status, message, result=None):
        now = self.now_func().isoformat(timespec="seconds")
        with self._lock:
            self._last_result = {
                "status": status,
                "message": message,
                "updated_at": now,
                **(result or {}),
            }

    def _write_log(self, message):
        if not self.log_path:
            return
        try:
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(f"{self.now_func().isoformat(timespec='seconds')} {message}\n")
        except OSError:
            pass
