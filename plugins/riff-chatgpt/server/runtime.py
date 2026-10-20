"""Private studio lifecycle and verified model setup for one MCP process.

The source studio keeps its loopback and origin checks. This managed process
never installs developer tools or changes another Riff installation.
"""
from __future__ import annotations
import contextlib
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import urllib.request


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def secret_service_session_available():
    """A command alone is insufficient on headless validation/build hosts."""
    if not shutil.which("secret-tool"):
        return False
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS") or os.environ.get("DISPLAY"):
        return True
    directory = os.environ.get("XDG_RUNTIME_DIR")
    return bool(directory and (Path(directory) / "bus").is_socket())


class SessionCredentials:
    """Process-local key shared with writing and review workers through stdin."""
    storage_name = "Session only — cleared when Riff closes"
    available = True

    def __init__(self):
        self._key = None
        self._lock = threading.RLock()

    def exists(self):
        with self._lock:
            return bool(self._key)

    def get(self):
        with self._lock:
            if not self._key:
                raise ValueError("Add your OpenRouter key in review settings for this session.")
            return self._key

    def set(self, key):
        if not isinstance(key, str) or not key.strip() or any(c.isspace() for c in key.strip()):
            raise ValueError("Enter your OpenRouter API key.")
        with self._lock:
            self._key = key.strip()

    def delete(self):
        with self._lock:
            self._key = None


class SetupCancelled(Exception):
    pass


class ManagedMaintenance:
    """The studio maintenance interface, scoped to pinned music-model downloads."""
    def __init__(self, source, workspace, generator, reviews, bundle=None):
        self.source, self.workspace = Path(source), Path(workspace)
        self.generator, self.reviews, self.bundle = generator, reviews, bundle
        self.video_exports = None
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.thread = self.response = None
        self.task = {"status": "idle", "message": ""}
        self.version = (self.source / "VERSION").read_text().strip()
        self.preferences = {"automatic_checks": False, "automatic_downloads": False,
                            "check_interval_seconds": 86400}
        self.manifest = json.loads((self.source / "sources.json").read_text())["model"]
        self.model_root = self.workspace / "models" / self.manifest["revision"]

    def busy(self):
        return bool(self.generator.has_active_work() or
                    (self.video_exports and self.video_exports.busy()) or
                    any(row["status"] in ("queued", "running", "cancelling")
                        for row in self.reviews.snapshot()))

    def snapshot(self):
        import platform_support
        with self.lock:
            return {"version": self.version, "engine": platform_support.readiness(),
                    "prerequisites": [], "desktop": False, "managed": True,
                    "plugin_managed": True,
                    "plugin_version": self.bundle.get("plugin_version") if self.bundle else "0.2.0",
                    "runtime_platform": self.bundle.get("platform") if self.bundle else None,
                    "task": dict(self.task), "preferences": dict(self.preferences),
                    "release": None, "pending": None, "busy": self.busy(),
                    "model_terms": {"name": "YuE2-3B", "license": "CC-BY-NC-4.0",
                                    "url": "https://huggingface.co/m-a-p/YuE2-3B"}}

    def configure(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"automatic_checks", "automatic_downloads"}:
            raise ValueError("Unknown plugin preference.")
        if any(type(value) is not bool for value in payload.values()):
            raise ValueError("Plugin preferences must be true or false.")
        if any(payload.values()):
            raise ValueError("ChatGPT manages plugin updates. Music models download when you choose Setup.")
        return self.snapshot()

    def apply_pending(self):
        # Handler sets restart_requested only after this returns. Keep MCP live.
        raise ValueError("ChatGPT applies plugin updates. Reopen Riff after updating the plugin.")

    def start(self, action, payload):
        if not isinstance(payload, dict):
            raise ValueError("Send setup options as an object.")
        if action in ("check", "update"):
            with self.lock:
                if self.task.get("status") == "running":
                    raise ValueError("A model download is already running.")
                self.task = {"status": "done", "action": "check",
                             "message": "ChatGPT manages updates to this plugin."}
            return self.snapshot()
        if action != "setup":
            raise ValueError("Unknown setup action.")
        if set(payload) - {"backend", "accept_model_terms"}:
            raise ValueError("Setup uses the bundled engine and only downloads music models.")
        import platform_support
        if payload.get("backend", platform_support.settings()["backend"]) != platform_support.settings()["backend"]:
            raise ValueError("Choose the plugin package built for your accelerator.")
        with self.lock:
            if self.task.get("status") == "running":
                raise ValueError("A model download is already running.")
            if self.busy() or not self.generator.quiesce():
                raise ValueError("Finish or cancel the current work before setting up music models.")
            self.cancelled.clear()
            self.task = {"status": "running", "action": "setup",
                         "message": "Checking the pinned YuE2 music models",
                         "received_bytes": 0,
                         "total_bytes": sum(item["bytes"] for item in self.manifest["files"].values()),
                         "progress": 0.0, "started": time.time()}
            self.thread = threading.Thread(target=self._download, name="riff-plugin-models", daemon=True)
            self.thread.start()
        return self.snapshot()

    def _check_cancel(self):
        if self.cancelled.is_set():
            raise SetupCancelled()

    def _progress(self, message, received=None):
        with self.lock:
            self.task["message"] = message
            if received is not None:
                self.task["received_bytes"] = received
                self.task["progress"] = received / max(1, self.task["total_bytes"])

    def _download(self):
        try:
            self.model_root.mkdir(parents=True, exist_ok=True)
            received_total = 0
            with (self.workspace / "data/setup.log").open("a", encoding="utf-8") as log:
                log.write(f"Pinned {self.manifest['repo']}@{self.manifest['revision']}\n")
                for name, expected in self.manifest["files"].items():
                    self._check_cancel()
                    target = self.model_root / name
                    if not target.resolve().is_relative_to(self.model_root.resolve()) or target.is_symlink():
                        raise ValueError("A model cache path is not an owned regular file.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.is_file() and target.stat().st_size == expected["bytes"] and file_hash(target) == expected["sha256"]:
                        received_total += expected["bytes"]
                        self._progress(f"Verified {name}", received_total)
                        continue
                    partial = target.with_name(target.name + ".part")
                    if partial.is_symlink() or (partial.exists() and not partial.is_file()):
                        raise ValueError("The partial model cache is not a regular file.")
                    received = partial.stat().st_size if partial.exists() else 0
                    if received > expected["bytes"]:
                        # This known-invalid cache cannot be resumed. Only the
                        # owned .part file is discarded; verified models remain.
                        partial.unlink()
                        received = 0
                    digest = hashlib.sha256()
                    if received:
                        with partial.open("rb") as stream:
                            for block in iter(lambda: stream.read(1024 * 1024), b""):
                                self._check_cancel()
                                digest.update(block)
                    if received == expected["bytes"] and digest.hexdigest() != expected["sha256"]:
                        partial.unlink()
                        received = 0
                        digest = hashlib.sha256()
                    if received < expected["bytes"]:
                        url = (f"https://huggingface.co/{self.manifest['repo']}/resolve/"
                               f"{self.manifest['revision']}/{name}")
                        request = urllib.request.Request(url, headers={"Range": f"bytes={received}-"} if received else {})
                        self._progress(f"Downloading {name}", received_total + received)
                        with urllib.request.urlopen(request, timeout=20) as response:
                            self.response = response
                            if received and (response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {received}-")):
                                raise ValueError("The model server did not honor the resume range.")
                            with partial.open("ab" if received else "wb") as stream:
                                while True:
                                    self._check_cancel()
                                    block = response.read(1024 * 1024)
                                    if not block:
                                        break
                                    received += len(block)
                                    if received > expected["bytes"]:
                                        raise ValueError(f"The download exceeds the pinned size: {name}")
                                    stream.write(block)
                                    digest.update(block)
                                    self._progress(f"Downloading {name}", received_total + received)
                                stream.flush()
                                os.fsync(stream.fileno())
                        self.response = None
                    self._check_cancel()
                    if received != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
                        if received == expected["bytes"]:
                            partial.unlink()
                        raise ValueError(f"Music-model size or SHA-256 verification failed: {name}")
                    partial.replace(target)
                    received_total += received
                    log.write(f"Verified {name}: {expected['sha256']}\n")
                    log.flush()
                write_json(self.model_root / "manifest.json", self.manifest)
                # The pinned native help probe needs model sidecars. A probe
                # before first setup caches missing features; refresh it now
                # that the verified model installation is complete.
                engine = sys.modules.get("run")
                if engine:
                    engine._engine_capabilities.cache_clear()
                self._progress("Music models verified. Ready to make music.", received_total)
                with self.lock:
                    self.task["status"] = "done"
        except SetupCancelled:
            with self.lock:
                self.task.update(status="cancelled", message="Setup cancelled. Verified files and partial downloads are kept.")
        except Exception as error:
            with self.lock:
                self.task.update(status="cancelled" if self.cancelled.is_set() else "failed", message=str(error))
            print(f"Riff model setup: {error}", file=sys.stderr)
        finally:
            self.response = None
            self.generator.resume()
            with self.lock:
                self.task["finished"] = time.time()

    def cancel(self):
        self.cancelled.set()
        return self.snapshot()

    def close(self):
        self.cancelled.set()
        if self.response:
            with contextlib.suppress(Exception):
                self.response.close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=25)


class ManagedRiff:
    def __init__(self, source: Path, workspace: Path, bundle=None, *, server_factory=None):
        self.source, self.workspace = source.resolve(), workspace.resolve()
        self.bundle_root = Path(os.environ["RIFF_PLUGIN_BUNDLE_ROOT"]) if os.environ.get("RIFF_PLUGIN_BUNDLE_ROOT") else None
        self.bundle = bundle or (json.loads((self.bundle_root / "runtime/runtime.json").read_text()) if self.bundle_root else None)
        self.server = self.generator = self.reviews = self.maintenance = None
        self.lock_file = self.thread = self.credentials = None
        self._original_keychain = None
        self._work_stopped = False
        self.server_factory = server_factory

    def __enter__(self):
        if not (self.source / "studio.py").is_file():
            raise RuntimeError("The Riff plugin is missing its bundled studio source.")
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        import fcntl
        lock_path = self.workspace / "chatgpt-adapter.lock"
        if lock_path.is_symlink():
            raise RuntimeError("The Riff plugin lock is not an owned regular file.")
        self.lock_file = lock_path.open("a+")
        try:
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("This Riff plugin workspace is already open in another process.") from None
            os.environ["RIFF_HOME"] = str(self.workspace)
            os.environ.pop("RIFF_INSTALL_ROOT", None)
            sys.path.insert(0, str(self.source))
            with contextlib.redirect_stdout(sys.stderr):
                paths = importlib.import_module("paths")
                if paths.WORKSPACE != self.workspace:
                    raise RuntimeError("A process may own only one Riff workspace. Start a separate plugin process.")
                paths.DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
                paths.OUTPUTS.mkdir(parents=True, exist_ok=True, mode=0o700)
                if self.bundle_root:
                    manifest = json.loads((self.source / "sources.json").read_text())["model"]
                    config_path = paths.DATA / "engine.json"
                    saved = json.loads(config_path.read_text()) if config_path.is_file() else {}
                    # Paths and backend follow the replaceable package. Only
                    # user tuning survives a package relocation or update.
                    settings = {"backend": self.bundle["backend"],
                                "binary": str(self.bundle_root / "runtime/engine/audiocpp_cli"),
                                "model_root": str(self.workspace / "models" / manifest["revision"]),
                                "model_file": "yue2-3b-q4_0.gguf", "vae_file": "yue2-vae-f16.gguf",
                                "threads": saved.get("threads", min(8, getattr(os, "process_cpu_count", os.cpu_count)() or 1)),
                                "device": saved.get("device", 0), "warm_engine": saved.get("warm_engine", False)}
                    write_json(config_path, settings)
                keychain = importlib.import_module("keychain")
                self._original_keychain = keychain.Keychain
                if sys.platform != "darwin" and not secret_service_session_available():
                    self.credentials = SessionCredentials()
                    keychain.Keychain = lambda *args, **kwargs: self.credentials
                else:
                    original = self._original_keychain
                    keychain.Keychain = lambda *args, **kwargs: original(service="Riff ChatGPT OpenRouter")
                studio = importlib.import_module("studio")
                store = studio.Store(paths.DATA, paths.OUTPUTS)
                store.import_existing()
                self.generator = studio.Generator(store)
                self.reviews = studio.Reviews(store, keychain=keychain.Keychain())
                self.maintenance = ManagedMaintenance(self.source, self.workspace, self.generator, self.reviews, self.bundle)
                self.server = (self.server_factory(studio, store, self.generator, self.reviews, self.maintenance)
                               if self.server_factory else
                               studio.StudioServer(("127.0.0.1", 0), store, self.generator,
                                                   self.reviews, self.maintenance))
            if self.server_factory:
                return self.server
            self.thread = threading.Thread(target=self.server.serve_forever, name="riff-plugin-http", daemon=True)
            self.thread.start()
            self.lock_file.seek(0)
            self.lock_file.truncate()
            json.dump({"pid": os.getpid(), "port": self.server.server_port}, self.lock_file)
            self.lock_file.flush()
            return self.server.server_port
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def snapshot(self):
        return self.maintenance.snapshot()

    def setup(self, payload=None):
        return self.maintenance.start("setup", payload or {})

    def stop_work(self):
        """Cancel owned work before waiting for in-flight MCP HTTP calls on EOF."""
        if self._work_stopped:
            return
        self._work_stopped = True
        for service in (self.maintenance, self.reviews, self.generator):
            if service:
                with contextlib.suppress(Exception):
                    service.close()

    def __exit__(self, *_):
        self.stop_work()
        if self.server and self.thread and self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=5)
        if self.server:
            with contextlib.suppress(Exception):
                self.server.server_close()
        if self.credentials:
            self.credentials.delete()
        if self._original_keychain:
            sys.modules["keychain"].Keychain = self._original_keychain
        if self.lock_file:
            self.lock_file.close()
