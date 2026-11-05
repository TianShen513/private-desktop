import copy
import io
import json
import unittest

from private_desktop.gateway import Gateway, MAX_INPUT_BYTES, SUPPORTED_PROTOCOLS
from private_desktop.privacy import TOKEN_PATTERN


SECRET = "private.person@example.com API_KEY=never-share"


def backend_snapshot(snapshot_id="s123"):
    return {"version": "2.6", "ok": True, "command": "snapshot", "data": {
        "snapshot_id": snapshot_id, "complete": True, "app": SECRET,
        "tree": {"role": "window", "name": SECRET, "children": [
            {"role": "textfield", "name": SECRET, "value": 123456789,
             "ref_id": "@" + snapshot_id + ":e1", "available_actions": ["SetValue"]},
            {"role": "button", "name": "Save", "ref_id": "@" + snapshot_id + ":e2",
             "available_actions": ["Click"]},
        ]}, "window": {"title": SECRET}, "unknown": {"nested": SECRET},
    }}


class FakeSandbox:
    app = "Pinned private app"

    def __init__(self):
        self.calls = []
        self.response = backend_snapshot()

    def run(self, command):
        self.calls.append(command)
        if isinstance(self.response, Exception):
            raise self.response
        return copy.deepcopy(self.response)


def request(method, params=None, request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = FakeSandbox()
        self.gateway = Gateway(self.sandbox)

    def call(self, name, arguments=None):
        return self.gateway.handle(request("tools/call", {"name": name, "arguments": arguments or {}}))

    def snapshot(self):
        return self.call("desktop_snapshot")

    def test_exactly_four_tools_and_supported_initialization(self):
        tools = self.gateway.handle(request("tools/list"))["result"]["tools"]
        self.assertEqual({tool["name"] for tool in tools}, {
            "desktop_snapshot", "desktop_click", "desktop_type", "desktop_status",
        })
        self.assertTrue(all(tool["inputSchema"]["additionalProperties"] is False for tool in tools))
        for protocol in SUPPORTED_PROTOCOLS:
            result = self.gateway.handle(request("initialize", {"protocolVersion": protocol}))
            self.assertEqual(result["result"]["protocolVersion"], protocol)
        self.assertIn("error", self.gateway.handle(request("initialize", {"protocolVersion": "unknown"})))
        self.assertEqual(self.gateway.handle(request("ping"))["result"], {})

    def test_both_mcp_copies_are_sanitized(self):
        response = self.snapshot()
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertNotIn(SECRET, json.dumps(response))
        self.assertNotIn("123456789", json.dumps(response))
        self.assertNotIn(self.sandbox.app, json.dumps(response))
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        self.assertEqual(self.sandbox.calls, [["snapshot", "--app", self.sandbox.app, "--compact"]])
        self.assertRegex(result["structuredContent"]["data"]["tree"]["name"], TOKEN_PATTERN)

    def test_unadvertised_tools_and_unknown_arguments_never_reach_backend(self):
        for name in ("desktop_launch", "desktop_batch", "desktop_get", "desktop_screenshot",
                     "desktop_clipboard_get", "desktop_trace_export", "private secret"):
            response = self.call(name, {"app": "Terminal"})
            self.assertTrue(response["result"]["isError"])
        for arguments in ({"app": "Terminal"}, {"headed": True}, {"output": "/secret"}, {"_meta": {}}):
            self.assertIn("error", self.call("desktop_snapshot", arguments))
        self.assertEqual(self.sandbox.calls, [])

    def test_foreign_refs_and_wrong_types_do_not_reach_backend(self):
        self.snapshot()
        for ref in ("@s999:e1", "@e1", "@s123:e999", True, {}, None, "@s123:e1\n"):
            response = self.call("desktop_click", {"ref": ref})
            self.assertTrue(response["result"]["isError"])
        self.assertEqual(len(self.sandbox.calls), 1)

    def test_actions_use_positional_arguments_and_invalidate_refs(self):
        self.snapshot()
        self.sandbox.response = {"ok": True, "command": "type", "data": {
            "post_state": {"value": SECRET}, "surfaces": [{"title": SECRET}],
            "disposition": {"delivery": "delivered_unverified", "retry": SECRET},
        }}
        response = self.call("desktop_type", {"ref": "@s123:e1", "text": "--headed"})
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(self.sandbox.calls[-1], ["type", "--", "@s123:e1", "--headed"])
        self.assertNotIn(SECRET, json.dumps(response))
        self.assertEqual(response["result"]["structuredContent"]["data"]["disposition"]["retry"], "unsafe")
        self.assertTrue(self.call("desktop_click", {"ref": "@s123:e2"})["result"]["isError"])
        self.assertEqual(len(self.sandbox.calls), 2)

    def test_token_typing_and_bad_text_are_blocked_without_restoration(self):
        response = self.snapshot()
        token = response["result"]["structuredContent"]["data"]["tree"]["name"]
        for text in (token, "prefix [PRIVATE_123]", "<EMAIL_1>", "{redacted:1}"):
            self.assertTrue(self.call("desktop_type", {"ref": "@s123:e1", "text": text})["result"]["isError"])
        for text in (False, 123, [], {}, "x" * 4097, "nul\x00text", "\ud800"):
            self.assertIn("error", self.call("desktop_type", {"ref": "@s123:e1", "text": text}))
        self.assertEqual(len(self.sandbox.calls), 1)

    def test_new_snapshot_replaces_old_ref_scope(self):
        self.snapshot()
        self.sandbox.response = backend_snapshot("s456")
        self.snapshot()
        self.assertTrue(self.call("desktop_click", {"ref": "@s123:e1"})["result"]["isError"])
        self.sandbox.response = {"ok": True, "command": "click", "data": {}}
        self.assertFalse(self.call("desktop_click", {"ref": "@s456:e2"})["result"]["isError"])

    def test_backend_errors_exceptions_and_malformed_responses_are_generic(self):
        for response in (RuntimeError(SECRET), {"ok": False, "command": "snapshot", "error": {"message": SECRET}},
                         {"ok": True, "command": "launch", "data": {"message": SECRET}},
                         {"ok": True, "command": "snapshot", "data": {"message": SECRET}},
                         {"ok": 1, "command": "snapshot", "data": {}}, [], SECRET):
            self.sandbox.response = response
            result = self.snapshot()
            self.assertTrue(result["result"]["isError"])
            self.assertNotIn(SECRET, json.dumps(result))
            self.assertFalse(self.gateway._refs)

    def test_status_does_not_forward_filesystem_paths_or_other_metadata(self):
        self.sandbox.response = {"ok": True, "command": "status", "data": {
            "state_root": "/home/private.person/.agent-desktop", "version": SECRET,
            "permissions": {"details": SECRET}, "snapshot_id": SECRET,
        }}
        response = self.call("desktop_status")
        data = response["result"]["structuredContent"]["data"]
        self.assertEqual(set(data), {"backend_available", "has_snapshot", "app"})
        self.assertNotIn(SECRET, json.dumps(response))
        self.assertNotIn("private.person", json.dumps(response))

    def test_output_size_bound_fails_closed_and_removes_action_refs(self):
        raw = backend_snapshot()
        raw["data"]["tree"]["children"] = [{
            "role": "button", "name": "hidden", "value": "hidden", "title": "hidden",
            "description": "hidden", "label": "hidden", "hint": "hidden",
            "ref_id": "@s123:e" + str(index),
        } for index in range(1, 1101)]
        self.sandbox.response = raw
        response = self.snapshot()
        self.assertEqual(response["error"]["code"], -32603)
        self.assertFalse(self.gateway._refs)
        self.assertTrue(self.call("desktop_click", {"ref": "@s123:e1"})["result"]["isError"])

    def test_unknown_methods_malformed_requests_and_notifications_do_not_act(self):
        for raw in ([], "secret", {"jsonrpc": "2.0", "id": {}, "method": "tools/list"},
                    request("resources/read", {"uri": "/secret"}),
                    {"jsonrpc": "1.0", "id": 1, "method": "tools/list"}):
            self.assertIn("error", self.gateway.handle(raw))
        self.assertIsNone(self.gateway.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(self.gateway.handle({"jsonrpc": "2.0", "method": "tools/call", "params": {
            "name": "desktop_snapshot", "arguments": {},
        }}))
        self.assertEqual(self.sandbox.calls, [])


class StdioTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = FakeSandbox()
        self.gateway = Gateway(self.sandbox)

    def test_stdio_only_emits_json_and_no_raw_diagnostics(self):
        self.sandbox.response = RuntimeError(SECRET)
        incoming = b'not json\n' + json.dumps(request("tools/call", {"name": "desktop_snapshot"})).encode() + b'\n'
        output = io.BytesIO()
        self.gateway.serve(io.BytesIO(incoming), output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertTrue(responses[1]["result"]["isError"])
        self.assertNotIn(SECRET.encode(), output.getvalue())

    def test_oversized_line_ends_session_before_following_commands(self):
        output = io.BytesIO()
        input_data = b"x" * (MAX_INPUT_BYTES + 1) + b"\n" + json.dumps(request("tools/call", {"name": "desktop_snapshot"})).encode() + b"\n"
        self.gateway.serve(io.BytesIO(input_data), output)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(self.sandbox.calls, [])

    def test_duplicate_keys_nonfinite_values_invalid_utf8_and_deep_json_fail(self):
        deep = "[" * 1100 + "0" + "]" * 1100
        lines = [b'{"jsonrpc":"2.0","id":1,"method":"ping","method":"tools/call"}',
                 b'{"jsonrpc":"2.0","id":NaN,"method":"ping"}', b'\xff', deep.encode()]
        output = io.BytesIO()
        self.gateway.serve(io.BytesIO(b"\n".join(lines) + b"\n"), output)
        self.assertEqual(len(output.getvalue().splitlines()), 4)
        self.assertTrue(all("error" in json.loads(line) for line in output.getvalue().splitlines()))
        self.assertEqual(self.sandbox.calls, [])

    def test_parse_failure_invalidates_existing_refs(self):
        self.gateway.handle(request("tools/call", {"name": "desktop_snapshot"}))
        self.assertTrue(self.gateway._refs)
        self.gateway.serve(io.BytesIO(b"not json\n"), io.BytesIO())
        self.assertFalse(self.gateway._refs)

    def test_text_streams_and_initialized_notification(self):
        output = io.StringIO()
        self.gateway.serve(io.StringIO('{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
                                      '{"jsonrpc":"2.0","id":2,"method":"ping"}\n'), output)
        self.assertEqual(json.loads(output.getvalue())["result"], {})


if __name__ == "__main__":
    unittest.main()
