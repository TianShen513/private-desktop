"""Docker lifecycle with an enforced, offline execution boundary."""

from __future__ import annotations

import importlib.resources
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

from .process import capture, ProcessError

IMAGE = "private-desktop:0.1.0"
APP = "privacy-demo"
LABEL = "io.github.private-desktop.owner"
TMPFS = {
    "/tmp": "rw,nosuid,nodev,noexec,size=256m,mode=1777",
    "/run": "rw,nosuid,nodev,noexec,size=64m,uid=1000,gid=1000,mode=700",
    "/home/desktop": "rw,nosuid,nodev,noexec,size=128m,uid=1000,gid=1000,mode=700",
}
ASSETS = ("Dockerfile", "entrypoint.sh", "demo.py", "checksums.txt", "AGENT_DESKTOP_LICENSE")


class SandboxError(Exception):
    """A stable diagnostic code, never raw backend text."""


def state_directory() -> Path:
    override = os.environ.get("PRIVATE_DESKTOP_HOME")
    path = Path(override).expanduser() if override else Path.home() / ".private-desktop"
    if not path.is_absolute() or path.is_symlink():
        raise SandboxError("unsafe_state_directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SandboxError("unsafe_state_directory")
    return path


def owner_id(directory: Path) -> str:
    path = directory / "owner"
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if path.is_symlink() or path.stat().st_size > 64:
            raise SandboxError("unsafe_owner_file")
        value = path.read_text(encoding="ascii").strip()
    else:
        value = uuid.uuid4().hex
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(value + "\n")
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise SandboxError("unsafe_owner_file")
    return value


class Sandbox:
    app = APP

    def __init__(self, directory: Path | None = None):
        self.directory = directory if directory is not None else state_directory()
        self.owner = owner_id(self.directory)
        self.name = "private-desktop-" + self.owner[:12]
        self.docker = shutil.which("docker")

    def docker_capture(self, args: list[str], *, timeout: float = 20) -> bytes:
        if self.docker is None:
            raise SandboxError("docker_not_installed")
        try:
            return capture([self.docker, *args], timeout=timeout)
        except ProcessError as exc:
            raise SandboxError(str(exc)) from None

    def check_engine(self) -> None:
        # Docker's context setting takes precedence over DOCKER_HOST.
        endpoint = None if os.environ.get("DOCKER_CONTEXT") else os.environ.get("DOCKER_HOST")
        if not endpoint:
            endpoint = self.docker_capture([
                "context", "inspect", "--format", "{{.Endpoints.docker.Host}}",
            ]).decode("utf-8").strip()
        if not endpoint.startswith(("unix://", "npipe://")):
            raise SandboxError("remote_docker_not_allowed")
        kind = self.docker_capture(["info", "--format", "{{.OSType}}"], timeout=15)
        if kind.strip() != b"linux":
            raise SandboxError("linux_containers_required")

    def inspect(self) -> dict:
        try:
            items = json.loads(self.docker_capture(["inspect", self.name]))
        except (ValueError, UnicodeError, SandboxError):
            raise SandboxError("sandbox_not_running") from None
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise SandboxError("invalid_sandbox")
        return items[0]

    def verify(self, item: dict | None = None) -> dict:
        item = self.inspect() if item is None else item
        config = item.get("Config") or {}
        host = item.get("HostConfig") or {}
        labels = config.get("Labels") or {}
        if labels.get(LABEL) != self.owner:
            raise SandboxError("unowned_container")
        checks = (
            item.get("State", {}).get("Running") is True,
            config.get("User") == "1000:1000",
            host.get("NetworkMode") == "none",
            host.get("ReadonlyRootfs") is True,
            host.get("Privileged") is False,
            "ALL" in (host.get("CapDrop") or []),
            not host.get("CapAdd"),
            any(option in ("no-new-privileges", "no-new-privileges:true")
                for option in (host.get("SecurityOpt") or [])),
            all(option in ("no-new-privileges", "no-new-privileges:true")
                for option in (host.get("SecurityOpt") or [])),
            not host.get("Binds"),
            not host.get("Devices"),
            not host.get("DeviceRequests"),
            not host.get("PortBindings"),
            host.get("PidMode", "") == "",
            host.get("IpcMode", "") in ("private", ""),
            host.get("UTSMode", "") == "",
            host.get("Memory", 0) > 0,
            0 < host.get("PidsLimit", 0) <= 512,
            host.get("NanoCpus", 0) > 0,
            host.get("Tmpfs") == TMPFS,
            set(item.get("NetworkSettings", {}).get("Networks", {"none": {}})) == {"none"},
            all(mount.get("Type") == "tmpfs" and mount.get("Destination") in TMPFS
                for mount in item.get("Mounts", [])),
            host.get("LogConfig", {}).get("Type") == "none",
        )
        if not all(checks):
            raise SandboxError("unsafe_container_configuration")
        return item

    def start_arguments(self) -> list[str]:
        args = [
            "run", "--detach", "--name", self.name, "--label", f"{LABEL}={self.owner}",
            "--pull", "never", "--network", "none", "--read-only", "--user", "1000:1000",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--pids-limit", "256", "--memory", "1g", "--cpus", "2", "--shm-size", "64m",
            "--log-driver", "none", "--restart", "no",
        ]
        for destination, options in TMPFS.items():
            args.extend(["--tmpfs", destination + ":" + options])
        return [*args, IMAGE]

    def start(self) -> dict:
        self.check_engine()
        try:
            existing = self.inspect()
        except SandboxError as exc:
            if str(exc) != "sandbox_not_running":
                raise
        else:
            if (existing.get("Config", {}).get("Labels") or {}).get(LABEL) != self.owner:
                raise SandboxError("unowned_container")
            if existing.get("State", {}).get("Running"):
                self.verify(existing)
                return self.status()
            self.docker_capture(["rm", self.name])
        try:
            self.docker_capture(self.start_arguments())
        except SandboxError:
            raise SandboxError("start_failed_build_image_first") from None
        try:
            for _ in range(30):
                self.verify()
                try:
                    self.docker_capture(["exec", self.name, "test", "-f", "/run/private-desktop/ready"])
                    return self.status()
                except SandboxError:
                    time.sleep(0.5)
            raise SandboxError("desktop_start_timeout")
        except BaseException:
            self.stop()
            raise

    def status(self) -> dict:
        self.check_engine()
        self.verify()
        return {"running": True, "network": "none", "shared_folders": False,
                "image": IMAGE, "app": self.app, "persistent_desktop_data": False}

    def stop(self) -> dict:
        self.check_engine()
        try:
            item = self.inspect()
        except SandboxError:
            return {"running": False}
        if (item.get("Config", {}).get("Labels") or {}).get(LABEL) != self.owner:
            raise SandboxError("unowned_container")
        self.docker_capture(["rm", "--force", self.name])
        return {"running": False, "desktop_state_removed": True}

    def run(self, command: list[str]) -> dict:
        self.check_engine()
        self.verify()
        output = self.docker_capture([
            "exec", self.name, "timeout", "--kill-after=2s", "10s", "agent-desktop", *command,
        ], timeout=15)
        try:
            envelope = json.loads(output)
        except (ValueError, UnicodeError):
            raise SandboxError("invalid_backend_output") from None
        if not isinstance(envelope, dict):
            raise SandboxError("invalid_backend_output")
        return envelope

    def build(self) -> None:
        self.check_engine()
        assert self.docker is not None
        assets = importlib.resources.files("private_desktop").joinpath("assets")
        with tempfile.TemporaryDirectory(prefix="private-desktop-build-") as temporary:
            for name in ASSETS:
                Path(temporary, name).write_bytes(assets.joinpath(name).read_bytes())
            result = subprocess.run(
                [self.docker, "build", "--tag", IMAGE, temporary], check=False,
            )
            if result.returncode:
                raise SandboxError("image_build_failed")
