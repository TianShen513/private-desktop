import copy
import io
import json
import os
from pathlib import Path
import socket
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from private_desktop import sandbox as sandbox_module
from private_desktop.sandbox import ASSETS, APP, LABEL, TMPFS, Sandbox, SandboxError, owner_id

LOCAL_ENGINE = {"DOCKER_HOST": "npipe:////./pipe/docker_engine", "DOCKER_CONTEXT": ""}


def safe_inspection(owner):
    return {
        "State": {"Running": True},
        "Config": {"User": "1000:1000", "Labels": {LABEL: owner}},
        "HostConfig": {
            "NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
            "CapDrop": ["ALL"], "CapAdd": None,
            "SecurityOpt": ["no-new-privileges:true"], "Binds": None,
            "Devices": [], "DeviceRequests": None, "PortBindings": {},
            "PidMode": "", "IpcMode": "private", "UTSMode": "",
            "Memory": 1073741824, "PidsLimit": 256, "NanoCpus": 2000000000,
            "Tmpfs": TMPFS.copy(), "LogConfig": {"Type": "none"},
        },
        "Mounts": [{"Type": "tmpfs", "Destination": key} for key in TMPFS],
    }


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.sandbox = Sandbox(Path(self.temporary.name))

    def test_owner_is_reused_without_desktop_content(self):
        self.assertEqual(self.sandbox.owner, owner_id(Path(self.temporary.name)))
        self.assertEqual([p.name for p in Path(self.temporary.name).iterdir()], ["owner"])

    def test_valid_container_passes(self):
        self.sandbox.verify(safe_inspection(self.sandbox.owner))

    def test_each_escape_setting_is_rejected(self):
        attacks = [
            ("NetworkMode", "bridge"), ("ReadonlyRootfs", False),
            ("Privileged", True), ("CapDrop", []), ("CapAdd", ["SYS_ADMIN"]),
            ("SecurityOpt", []), ("Binds", ["/var/run/docker.sock:/socket"]),
            ("SecurityOpt", ["no-new-privileges:true", "seccomp=unconfined"]),
            ("Devices", [{"PathOnHost": "/dev/mem"}]),
            ("DeviceRequests", [{"Count": -1}]),
            ("PortBindings", {"8080/tcp": [{"HostPort": "8080"}]}),
            ("PidMode", "host"), ("IpcMode", "host"), ("IpcMode", "container:other"),
            ("UTSMode", "host"),
            ("Memory", 0), ("PidsLimit", 0), ("PidsLimit", 10000),
            ("NanoCpus", 0), ("Tmpfs", {"/tmp": "rw"}),
            ("LogConfig", {"Type": "json-file"}),
        ]
        for key, value in attacks:
            with self.subTest(setting=key, value=value):
                item = safe_inspection(self.sandbox.owner)
                item["HostConfig"][key] = value
                with self.assertRaises(SandboxError):
                    self.sandbox.verify(item)

    def test_host_mount_disguised_as_safe_path_is_rejected(self):
        item = safe_inspection(self.sandbox.owner)
        item["Mounts"] = [{"Type": "bind", "Destination": "/tmp"}]
        with self.assertRaises(SandboxError):
            self.sandbox.verify(item)

    def test_additional_attached_network_is_rejected(self):
        item = safe_inspection(self.sandbox.owner)
        item["NetworkSettings"] = {"Networks": {"none": {}, "bridge": {}}}
        with self.assertRaises(SandboxError):
            self.sandbox.verify(item)

    def test_another_launchers_container_is_not_removed(self):
        item = safe_inspection("different-owner")
        with patch.object(self.sandbox, "check_engine"), \
                patch.object(self.sandbox, "inspect", return_value=item), \
                patch.object(self.sandbox, "docker_capture") as call:
            with self.assertRaises(SandboxError):
                self.sandbox.stop()
            call.assert_not_called()

    def test_launch_has_no_mount_or_network_options(self):
        args = self.sandbox.start_arguments()
        self.assertNotIn("--volume", args)
        self.assertNotIn("--mount", args)
        self.assertNotIn("--publish", args)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertEqual(args[args.index("--log-driver") + 1], "none")

    def test_remote_docker_host_rejected(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://remote.example:2376", "DOCKER_CONTEXT": ""}), \
                patch.object(self.sandbox, "docker_capture") as call:
            with self.assertRaises(SandboxError):
                self.sandbox.check_engine()
            call.assert_not_called()

    def test_context_cannot_hide_remote_endpoint_behind_local_host(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "unix:///local.sock", "DOCKER_CONTEXT": "remote"}), \
                patch.object(self.sandbox, "docker_capture", return_value=b"ssh://remote.example"):
            with self.assertRaises(SandboxError):
                self.sandbox.check_engine()

    def test_backend_argv_uses_no_shell(self):
        with patch.object(self.sandbox, "check_engine"), \
                patch.object(self.sandbox, "verify"), \
                patch.object(self.sandbox, "docker_capture", return_value=b'{"ok":true,"data":{}}') as call:
            self.sandbox.run(["type", "--", "@s123456:e1", "$(echo secret)"])
            call.assert_called_once_with([
                "exec", self.sandbox.name, "timeout", "--kill-after=2s", "10s", "agent-desktop",
                "type", "--", "@s123456:e1", "$(echo secret)",
            ], timeout=15)

    def test_backend_invalid_json_is_generic(self):
        with patch.object(self.sandbox, "check_engine"), \
                patch.object(self.sandbox, "verify"), \
                patch.object(self.sandbox, "docker_capture", return_value=b"RAW_PRIVATE_CONTENT"):
            with self.assertRaises(SandboxError) as raised:
                self.sandbox.run(["status"])
            self.assertNotIn("RAW_PRIVATE_CONTENT", str(raised.exception))


    def test_launch_requests_private_ipc(self):
        args = self.sandbox.start_arguments()
        self.assertEqual(args[args.index("--ipc") + 1], "private")

    def assert_engine_error(self, code):
        with self.assertRaises(SandboxError) as raised:
            self.sandbox.check_engine()
        self.assertEqual(str(raised.exception), code)

    @unittest.skipIf(os.name == "nt", "Unix sockets are not used for Docker on Windows")
    def test_missing_engine_socket_reports_stopped_engine(self):
        missing = Path(self.temporary.name, "missing.sock")
        with patch.dict(os.environ, {"DOCKER_HOST": f"unix://{missing}", "DOCKER_CONTEXT": ""}), \
                patch.object(self.sandbox, "docker_capture") as call:
            self.assert_engine_error("docker_not_running")
            call.assert_not_called()

    @unittest.skipIf(os.name == "nt", "Unix sockets are not used for Docker on Windows")
    def test_inaccessible_engine_socket_reports_permission(self):
        path = Path(self.temporary.name, "d.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(str(path))
        with patch.dict(os.environ, {"DOCKER_HOST": f"unix://{path}", "DOCKER_CONTEXT": ""}), \
                patch.object(sandbox_module.os, "access", return_value=False), \
                patch.object(self.sandbox, "docker_capture") as call:
            self.assert_engine_error("docker_permission_denied")
            call.assert_not_called()

    def test_engine_without_resource_limits_is_rejected(self):
        for info in (b"linux true true false\n", b"linux false true true\n", b"linux true\n"):
            with self.subTest(info=info), patch.dict(os.environ, LOCAL_ENGINE), \
                    patch.object(self.sandbox, "docker_capture", return_value=info):
                self.assert_engine_error("resource_limits_unavailable")

    def test_engine_info_checks_os_then_limits(self):
        with patch.dict(os.environ, LOCAL_ENGINE):
            with patch.object(self.sandbox, "docker_capture", return_value=b"windows true true true\n"):
                self.assert_engine_error("linux_containers_required")
            with patch.object(self.sandbox, "docker_capture", return_value=b"linux true true true\n"):
                self.sandbox.check_engine()

    def test_podman_docker_shim_is_named(self):
        def fake(args, **_):
            if args[0] == "--version":
                return b"podman version 5.6.0\n"
            raise SandboxError("process_failed")
        with patch.dict(os.environ, {"DOCKER_HOST": "", "DOCKER_CONTEXT": ""}), \
                patch.object(self.sandbox, "docker_capture", side_effect=fake):
            self.assert_engine_error("podman_not_supported")

    def test_context_failure_without_podman_keeps_code(self):
        def fake(args, **_):
            if args[0] == "--version":
                return b"Docker version 28.5.1, build e180ab8\n"
            raise SandboxError("process_failed")
        with patch.dict(os.environ, {"DOCKER_HOST": "", "DOCKER_CONTEXT": ""}), \
                patch.object(self.sandbox, "docker_capture", side_effect=fake):
            self.assert_engine_error("process_failed")

    def test_build_streams_recipe_without_host_paths(self):
        self.sandbox.docker = "docker"
        with patch.object(self.sandbox, "check_engine"), \
                patch.object(sandbox_module.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.sandbox.build()
        argv = run.call_args.args[0]
        self.assertEqual(argv, ["docker", "build", "--tag", sandbox_module.IMAGE, "-"])
        with tarfile.open(fileobj=io.BytesIO(run.call_args.kwargs["input"])) as archive:
            self.assertEqual(archive.getnames(), list(ASSETS))
            dockerfile = archive.extractfile("Dockerfile").read()
        self.assertIn(b"FROM ubuntu:24.04", dockerfile)

    def test_failed_build_is_reported(self):
        self.sandbox.docker = "docker"
        with patch.object(self.sandbox, "check_engine"), \
                patch.object(sandbox_module.subprocess, "run") as run:
            run.return_value.returncode = 1
            with self.assertRaises(SandboxError) as raised:
                self.sandbox.build()
        self.assertEqual(str(raised.exception), "image_build_failed")

if __name__ == "__main__":
    unittest.main()
