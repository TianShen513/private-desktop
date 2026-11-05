#!/usr/bin/env python3
"""Exercise the real offline GUI, not a mocked agent-desktop process.

Usage: python3 tests/smoke_sandbox.py private-desktop:0.1.0
Requires Docker and an already built image. The test always removes its container.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SENTINEL = "SYNTHETIC_PRIVATE_SENTINEL_7f39b2"
APP = "privacy-demo"


def docker(*args: str, text: str | None = None, timeout: float = 30) -> str:
    result = subprocess.run(
        ["docker", *args], input=text, text=True, capture_output=True, timeout=timeout
    )
    if result.returncode:
        # Avoid accidentally echoing GUI output into CI logs.
        raise RuntimeError(f"Docker {args[0]} failed (exit {result.returncode})")
    return result.stdout


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.get("children", []):
            yield from nodes(child)


def run(image: str) -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from private_desktop import sandbox as sandbox_module

    # The production launcher has a fixed image; never silently test another one.
    if image != sandbox_module.IMAGE:
        raise SystemExit(f"Test the production image: {sandbox_module.IMAGE}")
    with tempfile.TemporaryDirectory(prefix="private-desktop-smoke-") as temporary:
        directory = Path(temporary)
        sandbox = sandbox_module.Sandbox(directory)
        try:
            assert sandbox.start()["running"] is True
            exercise(sandbox, directory, root)
        finally:
            sandbox.stop()
        assert not docker("ps", "--all", "--filter", f"name=^/{sandbox.name}$", "--format", "{{.ID}}").strip()
    print("PASS: production lifecycle, real GUI actions, offline isolation, gateway and zipapp MCP redaction")


def exercise(sandbox, directory: Path, root: Path) -> None:
    from private_desktop.gateway import Gateway

    name = sandbox.name
    info = sandbox.verify()
    host = info["HostConfig"]
    assert host["NetworkMode"] == "none"
    assert host["ReadonlyRootfs"] is True
    assert info["Config"]["User"] == "1000:1000"
    assert host["CapDrop"] == ["ALL"]
    assert "no-new-privileges:true" in host["SecurityOpt"]
    assert not host.get("Binds") and not host.get("PortBindings")
    assert {mount["Type"] for mount in info["Mounts"]} <= {"tmpfs"}
    assert host["PidsLimit"] == 256
    assert host["Memory"] == 1024**3
    assert host["LogConfig"]["Type"] == "none"
    assert all("noexec" in options.split(",") for options in host["Tmpfs"].values())

    def agent(*args: str):
        result = sandbox.run(list(args))
        assert result.get("ok"), f"agent-desktop {args[0]} failed"
        return result

    snapshot = agent("snapshot", "--app", APP, "--compact")
    assert SENTINEL in json.dumps(snapshot), "Synthetic redaction fixture absent"
    entry = next(n for n in nodes(snapshot["data"]["tree"]) if n.get("name") == "Demo note")
    assert entry.get("ref_id"), "Demo input has no actionable ref"
    # v1.1.0 predates upstream's --stdin option. This input is synthetic/public.
    agent("type", "--", entry["ref_id"], "sandbox smoke note")
    snapshot = agent("snapshot", "--app", APP, "--compact")
    save = next(n for n in nodes(snapshot["data"]["tree"]) if n.get("name") == "Save note")
    agent("click", save["ref_id"])
    snapshot = agent("snapshot", "--app", APP, "--compact")
    assert "Saved: sandbox smoke note" in json.dumps(snapshot), "Actual GTK click/type did not update app"

    # Verify kernel-visible boundaries inside the running workload.
    probe = '''import errno, os, pathlib, socket
assert os.getuid() == 1000
status = pathlib.Path('/proc/self/status').read_text()
assert 'CapEff:\\t0000000000000000' in status
assert 'NoNewPrivs:\\t1' in status
assert not pathlib.Path('/var/run/docker.sock').exists()
assert not pathlib.Path('/run/docker.sock').exists()
assert not list(pathlib.Path('/run/private-desktop').rglob('*.jsonl'))
try:
    pathlib.Path('/usr/local/root-write-test').write_text('test')
except OSError as e:
    assert e.errno in (errno.EROFS, errno.EACCES)
else:
    raise AssertionError('Root filesystem is writable')
sock = socket.socket()
sock.settimeout(2)
try:
    sock.connect(('1.1.1.1', 443))
except OSError as e:
    assert e.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH)
else:
    raise AssertionError('External networking unexpectedly works')
finally:
    sock.close()
'''
    docker("exec", "--interactive", name, "python3", "-", text=probe)

    # Run the actual host gateway over this already hardened test container.
    # The synthetic secret is present in the real GTK tree but must never leave
    # the projection in plaintext. Raw snapshots stay local and are not printed.
    gateway = Gateway(sandbox, safe_labels=("Demo note", "Save note"))

    def call(tool, arguments=None):
        response = gateway.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        })
        encoded = json.dumps(response)
        assert SENTINEL not in encoded, "Gateway exposed synthetic private text"
        assert "sandbox smoke note" not in encoded, "Gateway exposed entry content"
        assert response is not None and "result" in response, "Gateway RPC failed"
        assert not response["result"]["isError"], "Gateway action failed"
        return response["result"]["structuredContent"]

    safe = call("desktop_snapshot")
    assert "<PRIVATE:" in json.dumps(safe), "Private fields were not tokenized"
    assert "Private Desktop Demo" not in json.dumps(safe), "Window title escaped projection"
    safe_entry = next(n for n in nodes(safe["data"]["tree"]) if n.get("name") == "Demo note")
    call("desktop_type", {"ref": safe_entry["ref_id"], "text": " public gateway note"})
    safe = call("desktop_snapshot")
    safe_save = next(n for n in nodes(safe["data"]["tree"]) if n.get("name") == "Save note")
    call("desktop_click", {"ref": safe_save["ref_id"]})
    assert "public gateway note" in json.dumps(agent("snapshot", "--app", APP, "--compact"))
    call("desktop_snapshot")

    # Build the production standalone archive and exercise the actual stdio
    # entry point against the same production-owned sandbox.
    package = subprocess.run(
        [sys.executable, str(root / "tools" / "build_zipapp.py")],
        capture_output=True, text=True, timeout=30, cwd=root,
    )
    assert package.returncode == 0, "Standalone archive build failed"
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "desktop_snapshot"}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "desktop_launch"}},
    ]
    client = subprocess.run(
        [sys.executable, str(root / "dist" / "private-desktop.pyz"), "mcp"],
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "PRIVATE_DESKTOP_HOME": str(directory)},
    )
    assert client.returncode == 0, "Standalone MCP server exited unsuccessfully"
    assert not client.stderr, "MCP server emitted unexpected diagnostics"
    assert SENTINEL not in client.stdout and "public gateway note" not in client.stdout
    responses = [json.loads(line) for line in client.stdout.splitlines()]
    assert [response["id"] for response in responses] == [1, 2, 3, 4]
    assert len(responses[1]["result"]["tools"]) == 4
    assert responses[2]["result"]["structuredContent"]["ok"] is True
    assert "<PRIVATE:" in json.dumps(responses[2])
    assert responses[3]["result"]["isError"] is True
    sandbox.verify()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 tests/smoke_sandbox.py IMAGE")
    run(sys.argv[1])
