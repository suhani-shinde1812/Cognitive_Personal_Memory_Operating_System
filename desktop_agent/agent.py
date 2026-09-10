# LOCATION: desktop_agent/agent.py
"""
agent.py
========
CogniSphere Desktop Agent — Main Runner.
Synchronizes user-authorized Windows folders with CogniSphere Web and Backend.
Features:
- Explicit permission setup wizard
- SHA-256 deduplication
- Watchdog real-time file monitoring
- Offline resilient queue with retry
- Secure pairing with CogniSphere backend
"""

from __future__ import annotations
import os
import sys
import time
import signal
import argparse
import threading
from pathlib import Path
from datetime import datetime, timezone

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from desktop_agent.config import AgentConfig
from desktop_agent.scanner import FolderScanner, LocalManifest
from desktop_agent.watcher import WatcherManager
from desktop_agent.sync_queue import SyncQueue
from desktop_agent.client import BackendClient


class DesktopAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.client = BackendClient(config)
        self.queue = SyncQueue()
        self.manifest = LocalManifest()
        self.scanner = FolderScanner(self.manifest)
        self.watcher = WatcherManager(self.queue)
        self.running = False
        self._worker_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._scan_thread: threading.Thread | None = None

    def run_permission_wizard(self) -> None:
        """Interactive setup wizard for folder permissions on first run."""
        print("\n" + "=" * 60)
        print("  CogniSphere Desktop Agent — File & Memory Sync")
        print("=" * 60)
        print("\nWelcome to CogniSphere!")
        print("Choose which folders CogniSphere has permission to access:\n")

        for idx, f in enumerate(self.config.watched_folders, start=1):
            status = "[X]" if f.get("enabled") else "[ ]"
            print(f"  {idx}. {status} {f['name']} ({f['path']})")

        print("\nOptions:")
        print("  - Enter numbers separated by commas to toggle (e.g., 1, 2)")
        print("  - Enter 'c' to add a custom folder path")
        print("  - Press Enter to continue with current selection")

        try:
            choice = input("\nYour selection: ").strip()
            if choice.lower() == "c":
                custom_path = input("Enter custom folder path: ").strip()
                if self.config.add_custom_folder(custom_path):
                    print(f"Added and enabled: {custom_path}")
                else:
                    print("Invalid directory path.")
            elif choice:
                parts = [p.strip() for p in choice.split(",") if p.strip()]
                for p in parts:
                    if p.isdigit():
                        idx = int(p) - 1
                        if 0 <= idx < len(self.config.watched_folders):
                            curr = self.config.watched_folders[idx].get("enabled", False)
                            self.config.watched_folders[idx]["enabled"] = not curr
                            status = "Enabled" if not curr else "Disabled"
                            print(f"{status}: {self.config.watched_folders[idx]['name']}")
                self.config.save()
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")

        enabled_count = len(self.config.get_enabled_folders())
        print(f"\nConfiguration saved. {enabled_count} folder(s) authorized for sync.\n")

    def is_path_authorized(self, file_path: str) -> bool:
        """Checks if a file path belongs to an authorized, currently enabled folder."""
        if not file_path:
            return False
        p = Path(file_path).resolve()
        for f in self.config.get_enabled_folders():
            folder_p = Path(f["path"]).resolve()
            try:
                p.relative_to(folder_p)
                return True
            except ValueError:
                continue
        return False

    def sync_with_server_permissions(self) -> None:
        """Fetches authorized locations from backend and updates local folder statuses."""
        if not self.config.is_paired():
            return
        locations = self.client.fetch_authorized_locations()
        if not locations:
            return

        loc_map = {Path(l["path"]).resolve(): l for l in locations if "path" in l}
        changed = False

        for f in self.config.watched_folders:
            f_path = Path(f["path"]).resolve()
            if f_path in loc_map:
                srv = loc_map[f_path]
                server_enabled = bool(srv.get("enabled", True) and srv.get("permission_status") == "granted")
                if f.get("enabled") != server_enabled:
                    f["enabled"] = server_enabled
                    changed = True

        existing_paths = {Path(f["path"]).resolve() for f in self.config.watched_folders}
        for srv_path, srv in loc_map.items():
            if srv_path not in existing_paths and srv_path.exists():
                self.config.watched_folders.append({
                    "id": f"srv_{srv.get('id', len(self.config.watched_folders)+1)}",
                    "name": srv.get("display_name", srv_path.name),
                    "path": str(srv_path),
                    "enabled": bool(srv.get("enabled", True) and srv.get("permission_status") == "granted"),
                    "status": "idle",
                    "file_count": 0,
                })
                changed = True

        if changed:
            self.config.save()
            if self.running and not self.config.is_paused:
                self.watcher.start(self.config.get_enabled_folders())

    def ensure_paired(self, pairing_code: Optional[str] = None, auth_token: Optional[str] = None) -> bool:
        """Ensures the agent is paired with the backend using pairing code or token."""
        if self.config.is_paired() and not pairing_code and not auth_token:
            if self.client.verify_credentials():
                return True
            print("[Agent] Saved device credentials were rejected by server (expired or reset). Re-pairing...")
            self.config.device_id = ""
            self.config.auth_token = ""
            self.config.save()

        if not pairing_code and not auth_token:
            try:
                code_input = input("\nEnter CogniSphere Pairing Code from Web UI (or press Enter to pair directly): ").strip()
                if code_input:
                    pairing_code = code_input
            except (KeyboardInterrupt, EOFError):
                pass

        print(f"[Agent] Pairing with backend: {self.config.server_url} ...")
        res = self.client.pair_device(
            device_name=self.config.device_name,
            os_info=self.config.os_info,
            pairing_code=pairing_code,
            auth_token=auth_token,
        )
        if res and res.get("device_id") and res.get("auth_token"):
            self.config.device_id = res["device_id"]
            self.config.auth_token = res["auth_token"]
            self.config.save()
            print(f"[Agent] Successfully paired! Device ID: {self.config.device_id}")
            self.sync_with_server_permissions()
            return True

        print(f"[Agent] Pairing failed. Verify backend is running at {self.config.server_url}")
        return False

    def perform_scan(self) -> dict:
        """Scans all enabled folders and enqueues sync jobs."""
        self.sync_with_server_permissions()
        enabled = self.config.get_enabled_folders()
        if not enabled:
            print("[Agent] No folders enabled for scanning.")
            return {"scanned": 0, "enqueued": 0}

        print(f"\n[Agent] Starting scan across {len(enabled)} authorized folder(s)...")
        total_added = 0
        total_modified = 0
        total_deleted = 0
        total_found = 0

        for f in enabled:
            print(f"  Scanning: {f['name']} ...")
            diff = self.scanner.scan_folder(f["path"], f["name"])
            f["file_count"] = diff["total_found"]
            total_found += diff["total_found"]

            # Enqueue added
            for item in diff["added"]:
                self.queue.enqueue("SYNC", item)
                total_added += 1

            # Enqueue modified
            for item in diff["modified"]:
                self.queue.enqueue("SYNC", item)
                total_modified += 1

            # Enqueue deleted
            for item in diff["deleted"]:
                self.queue.enqueue("DELETE", item)
                total_deleted += 1

        self.config.save()
        print(f"[Agent] Scan complete: {total_found} files found | "
              f"+{total_added} new, ~{total_modified} modified, -{total_deleted} deleted.\n")

        return {
            "total_found": total_found,
            "added": total_added,
            "modified": total_modified,
            "deleted": total_deleted,
        }

    def _queue_worker_loop(self) -> None:
        """Processes jobs from the local persistent sync queue with concurrent uploads."""
        import concurrent.futures
        CONCURRENCY = 5      # Upload 5 files at once
        BATCH_SIZE  = 20     # Fetch 20 jobs per iteration
        PACE_DELAY  = 0.3    # Seconds between batches (not per-file)

        while self.running:
            jobs = self.queue.get_pending(limit=BATCH_SIZE)
            if not jobs:
                time.sleep(2)
                continue

            sync_jobs   = [j for j in jobs if j["job_type"] == "SYNC"]
            delete_jobs = [j for j in jobs if j["job_type"] == "DELETE"]

            def _do_sync(job):
                """Upload one file; returns (job_id, success, stop_agent)."""
                if not self.running:
                    return job["id"], False, False
                payload = job["payload"]
                abs_path = payload.get("abs_path")
                if not self.is_path_authorized(abs_path):
                    print(f"[Sync] Skipping (not authorized): {payload.get('filename')}")
                    self.queue.mark_done(job["id"])
                    return job["id"], True, False

                res = self.client.sync_file(
                    file_path=abs_path,
                    relative_path=payload.get("relative_path"),
                    sha256_hash=payload.get("sha256"),
                    modified_at=(
                        datetime.fromtimestamp(payload["mtime"], tz=timezone.utc).isoformat()
                        if payload.get("mtime") else None
                    ),
                )
                if res and res.get("success"):
                    self.queue.mark_done(job["id"])
                    self.manifest.set(abs_path, {
                        "relative_path": payload.get("relative_path"),
                        "sha256": payload.get("sha256"),
                        "mtime": payload.get("mtime"),
                        "memory_id": res.get("memory_id"),
                        "synced_at": datetime.now(timezone.utc).isoformat(),
                    })
                    print(f"[Sync] ✓ {payload.get('filename')} → Memory #{res.get('memory_id')}")
                    return job["id"], True, False
                elif res and res.get("status_code") == 401:
                    return job["id"], False, True   # signal stop
                else:
                    self.queue.mark_failed(job["id"], "Upload failed")
                    return job["id"], False, False

            # Run SYNC jobs concurrently
            if sync_jobs:
                with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
                    futures = {ex.submit(_do_sync, j): j for j in sync_jobs}
                    for fut in concurrent.futures.as_completed(futures):
                        try:
                            _, ok, stop_agent = fut.result()
                            if stop_agent:
                                print("\n[Agent] ⚠️ 401 from server — resetting pairing credentials.")
                                self.config.device_id = ""
                                self.config.auth_token = ""
                                self.config.save()
                                self.running = False
                                return
                        except Exception as fe:
                            print(f"[Sync] Worker error: {fe}")

            # Process DELETE jobs sequentially (rare)
            for job in delete_jobs:
                if not self.running:
                    break
                rel_path = job["payload"].get("relative_path")
                abs_path = job["payload"].get("abs_path")
                if self.client.delete_file(rel_path):
                    self.queue.mark_done(job["id"])
                    if abs_path:
                        self.manifest.remove(abs_path)
                    print(f"[Sync] Removed from index: {rel_path}")
                else:
                    self.queue.mark_failed(job["id"], "Delete request failed")

            # Show queue depth every batch so user knows progress
            remaining = self.queue.count_pending()
            if remaining > 0:
                print(f"[Agent] Queue: {remaining} files remaining...")

            time.sleep(PACE_DELAY)


    def _heartbeat_loop(self) -> None:
        """Reports periodic heartbeat to the CogniSphere backend."""
        while self.running:
            try:
                status = "watching" if self.watcher.is_alive() else "idle"
                if self.config.is_paused:
                    status = "paused"

                self.client.send_heartbeat(
                    status=status,
                    folders=self.config.watched_folders,
                )
            except Exception:
                pass
            time.sleep(self.config.heartbeat_interval)

    def _periodic_scan_loop(self) -> None:
        """Runs periodic incremental scans in the background."""
        while self.running:
            time.sleep(self.config.scan_interval)
            if not self.running or self.config.is_paused:
                continue
            try:
                self.perform_scan()
            except Exception as e:
                print(f"[Agent] Periodic scan error: {e}")

    def start(self) -> None:
        """Starts the desktop agent in background threads."""
        self.running = True

        # 1. Start queue worker
        self._worker_thread = threading.Thread(target=self._queue_worker_loop, daemon=True)
        self._worker_thread.start()

        # 2. Start heartbeat
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

        # 3. Start real-time folder watcher
        if not self.config.is_paused:
            self.watcher.start(self.config.get_enabled_folders())

        # 4. Start periodic scanner
        self._scan_thread = threading.Thread(target=self._periodic_scan_loop, daemon=True)
        self._scan_thread.start()

        print("[Agent] Desktop Agent is active and running.")

    def stop(self) -> None:
        """Stops all watcher threads and worker loops gracefully."""
        print("\n[Agent] Stopping CogniSphere Desktop Agent...")
        self.running = False
        self.watcher.stop()
        print("[Agent] Agent stopped cleanly.")


def main():
    parser = argparse.ArgumentParser(description="CogniSphere Desktop File & Memory Sync Agent")
    parser.add_argument("--server", help="CogniSphere backend URL", default=None)
    parser.add_argument("--headless", action="store_true", help="Run without interactive wizard")
    parser.add_argument("--scan-now", action="store_true", help="Perform immediate scan and exit")
    parser.add_argument("--status", action="store_true", help="Show current sync status")
    parser.add_argument("--add-folder", help="Add and authorize a custom folder for synchronization")
    parser.add_argument("--enable-all-defaults", action="store_true", help="Enable all standard user folders")
    parser.add_argument("--pair-code", "--code", help="CogniSphere Web pairing code (e.g. COG-1234)", default=None)
    parser.add_argument("--token", help="Pre-shared device auth token from CogniSphere Web", default=None)
    parser.add_argument("--reset", action="store_true", help="Reset local device pairing and clear sync queue")
    args = parser.parse_args()

    config = AgentConfig()

    if args.reset:
        config.device_id = ""
        config.auth_token = ""
        config.save()
        from desktop_agent.sync_queue import SyncQueue
        SyncQueue().clear()
        print("[Agent] Local pairing and sync queue reset successfully.")
        return

    if args.server:
        config.server_url = args.server
        config.save()

    if args.enable_all_defaults:
        for f in config.watched_folders:
            f["enabled"] = True
        config.save()
        print("[Config] Enabled all default folders.")

    if args.add_folder:
        if config.add_custom_folder(args.add_folder):
            print(f"[Config] Added custom folder: {args.add_folder}")
        else:
            print(f"[Config] Failed to add folder: {args.add_folder}")
        return

    agent = DesktopAgent(config)

    if args.status:
        print("\n--- CogniSphere Desktop Agent Status ---")
        print(f"Server URL:     {config.server_url}")
        print(f"Device Name:    {config.device_name}")
        print(f"Device ID:      {config.device_id or '(Not Paired)'}")
        print(f"Backend Status: {'Online' if agent.client.check_health() else 'Offline'}")
        print(f"Pending Queue:  {agent.queue.count_pending()} files")
        print("\nAuthorized Folders:")
        for f in config.watched_folders:
            status = "Watching" if f.get("enabled") else "Disabled"
            print(f"  - {f['name']}: {status} ({f.get('file_count', 0)} files) [{f['path']}]")
        print("-" * 40 + "\n")
        return

    # First run setup wizard if not headless and no folders enabled
    if not args.headless and not config.get_enabled_folders():
        agent.run_permission_wizard()

    # Ensure paired
    if not agent.ensure_paired(pairing_code=args.pair_code, auth_token=args.token):
        print("[Agent] Could not pair with backend. Exiting.")
        sys.exit(1)

    # Initial scan
    agent.perform_scan()

    if args.scan_now:
        # Wait for queue to drain
        print("[Agent] Processing queued jobs...")
        agent.running = True
        t = threading.Thread(target=agent._queue_worker_loop, daemon=True)
        t.start()
        while agent.queue.count_pending() > 0:
            time.sleep(0.5)
        agent.running = False
        print("[Agent] Immediate scan and ingestion completed.")
        return

    # Normal daemon run
    agent.start()

    # Handle graceful Ctrl+C
    def sig_handler(sig, frame):
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    print("[Agent] Running in background. Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        agent.stop()


if __name__ == "__main__":
    main()
