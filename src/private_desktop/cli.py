"""Cross-platform launcher. MCP stdout is reserved for protocol messages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .sandbox import Sandbox, SandboxError

MESSAGES = {
    "docker_not_installed": "Install Docker (Docker Desktop on macOS/Windows, Docker Engine on Linux) and start it, then retry.",
    "process_failed": "Docker could not complete the operation. Check the Docker engine is running.",
    "process_unavailable": "Docker could not be started. Check your installation.",
    "process_timeout": "Docker timed out. Check the Docker engine and retry.",
    "output_limit": "A backend response exceeded the permitted size.",
    "linux_containers_required": "Switch Docker Desktop to Linux containers.",
    "remote_docker_not_allowed": "Select a local Docker context; remote Docker is disabled.",
    "docker_not_running": ("The Docker engine is not running. Start Docker Desktop, or on Linux run "
                           "'systemctl --user start docker' (rootless) or 'sudo systemctl start docker'."),
    "docker_permission_denied": ("This user cannot open the Docker socket. On Linux, use rootless Docker "
                                 "or join the docker group, then log in again. See README, Linux hosts."),
    "resource_limits_unavailable": ("Docker cannot enforce CPU, memory, and process limits here. For rootless "
                                    "Docker, delegate cgroup v2 controllers. See README, Linux hosts."),
    "podman_not_supported": "Podman is not supported yet. Install Docker Engine (rootless works).",
    "sandbox_not_running": "Run private-desktop build, then private-desktop start.",
    "start_failed_build_image_first": "Run private-desktop build before starting the desktop.",
    "desktop_start_timeout": "The desktop did not become ready. Stop it and rebuild the image.",
    "unsafe_container_configuration": "The container failed isolation checks. Stop and recreate it.",
    "unowned_container": "The container is not owned by this launcher. It was left untouched.",
    "unsafe_state_directory": "Use a private directory you own for PRIVATE_DESKTOP_HOME (mode 700 on Unix).",
    "unsafe_owner_file": "The local launcher ownership file is invalid. Review ~/.private-desktop/owner.",
    "image_build_failed": "The image build failed. Check the build output and your network connection.",
    "invalid_backend_output": "The desktop returned an invalid response.",
}


def write_json(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=True, separators=(",", ":")))


def client_config() -> dict:
    invocation = Path(sys.argv[0])
    arguments = ([str(invocation.resolve()), "mcp"] if invocation.suffix == ".pyz"
                 else ["-m", "private_desktop", "mcp"])
    return {"mcpServers": {"private-desktop": {"command": sys.executable, "args": arguments}}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="private-desktop", description="An offline desktop with filtered agent access.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("command", choices=[
        "doctor", "build", "start", "status", "stop", "mcp", "demo", "client-config",
    ])
    args = parser.parse_args(argv)
    if args.command == "client-config":
        write_json(client_config())
        return 0
    try:
        sandbox = Sandbox()
        if args.command == "mcp":
            from .gateway import Gateway
            Gateway(sandbox).serve()
        elif args.command == "build":
            sandbox.build()
            write_json({"ok": True, "image_built": True})
        elif args.command == "doctor":
            sandbox.check_engine()
            write_json({"ok": True, "python": ".".join(map(str, sys.version_info[:3])),
                        "docker": "local-linux", "version": __version__})
        elif args.command in ("start", "stop", "status"):
            write_json({"ok": True, **getattr(sandbox, args.command)()})
        elif args.command == "demo":
            from .gateway import Gateway
            gateway = Gateway(sandbox)
            # The demo deliberately uses the same boundary as a remote MCP client.
            result = gateway.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": "desktop_snapshot", "arguments": {}}})
            write_json(result)
            if not result or "error" in result or result.get("result", {}).get("isError"):
                return 1
    except KeyboardInterrupt:
        return 130
    except (SandboxError, OSError, ValueError) as exc:
        code = str(exc) if isinstance(exc, SandboxError) else "local_operation_failed"
        message = MESSAGES.get(code, "The operation failed. No backend output was forwarded.")
        print(f"private-desktop: {message}", file=sys.stderr)
        return 1
    return 0
