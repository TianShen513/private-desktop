import json
import unittest

from private_desktop.privacy import (
    MAX_NODES, MAX_STRING_LENGTH, TOKEN_PATTERN, PrivacyError, SnapshotProjector,
    TokenVault, contains_private_placeholder, validate_json,
)


def snapshot(tree=None, snapshot_id="s123"):
    return {"ok": True, "command": "snapshot", "data": {
        "app": "Private application", "snapshot_id": snapshot_id, "complete": True,
        "tree": tree if tree is not None else {"role": "window"},
    }}


class TokenVaultTests(unittest.TestCase):
    def test_tokens_are_random_stable_session_scoped_and_not_restorable(self):
        first, second = TokenVault(), TokenVault()
        token = first.token("person@example.com")
        self.assertRegex(token, TOKEN_PATTERN)
        self.assertEqual(first.token("person@example.com"), token)
        self.assertNotEqual(second.token("person@example.com"), token)
        self.assertNotEqual(first.token(1234), first.token("1234"))
        self.assertNotIn("person@example.com", repr(first.__dict__))
        self.assertFalse(hasattr(first, "restore"))

    def test_vault_is_bounded(self):
        vault = TokenVault(max_tokens=1)
        first = vault.token("first")
        self.assertEqual(vault.token("first"), first)
        with self.assertRaises(PrivacyError):
            vault.token("second")

    def test_placeholder_detection(self):
        for value in ("<PRIVATE:abc>", "[PRIVATE_1]", "prefix <email_2>", "{redacted:1}"):
            self.assertTrue(contains_private_placeholder(value))
        self.assertFalse(contains_private_placeholder("A literal public note."))


class ProjectionTests(unittest.TestCase):
    def test_nested_secrets_numeric_values_and_metadata_do_not_escape(self):
        projector = SnapshotProjector(["Save"])
        raw = snapshot({"role": "window", "name": "Secret Account", "children": [
            {"role": "textfield", "name": "person@example.com", "value": 123456789,
             "description": {"nested": "private description"}, "hint": "secret hint",
             "ref_id": "@s123:e1", "native_id": {"value": "API_KEY=secret"},
             "metadata": ["metadata secret"], "bounds": {"x": 445566, "y": 99999}},
            {"role": "button", "name": "Save", "value": "Save", "ref_id": "@s123:e2",
             "available_actions": ["Click", "private action"],
             "states": ["focused", "state secret"]},
        ]})
        raw["data"]["window"] = {"id": "private-window-id", "title": "private title"}
        raw["data"]["extra"] = {"arbitrary": "extra secret"}
        result, refs = projector.project(raw, "Pinned private app")
        encoded = json.dumps(result)
        for value in ("Secret Account", "person@example.com", "123456789", "private description",
                      "secret hint", "API_KEY", "metadata secret", "445566", "private action",
                      "state secret", "private-window-id", "private title", "extra secret",
                      "Pinned private app"):
            self.assertNotIn(value, encoded)
        self.assertEqual(refs, {"@s123:e1", "@s123:e2"})
        self.assertEqual(result["tree"]["children"][1]["name"], "Save")
        self.assertRegex(result["tree"]["children"][1]["value"], TOKEN_PATTERN)
        self.assertEqual(result["tree"]["children"][1]["states"], {"focused": True})
        self.assertNotIn("native_id", encoded)
        self.assertNotIn("bounds", encoded)

    def test_unknown_roles_are_hidden_and_boolean_states_are_vetted(self):
        projector = SnapshotProjector([])
        projected, _ = projector.project(snapshot({"role": "a private custom role",
            "states": {"focused": True, "disabled": False, "private-state": True}}), "app")
        self.assertRegex(projected["tree"]["role"], TOKEN_PATTERN)
        self.assertEqual(projected["tree"]["states"], {"focused": True, "disabled": False})

    def test_label_allowlist_is_exact_and_values_always_hidden(self):
        projector = SnapshotProjector(["Save"])
        result, _ = projector.project(snapshot({"role": "button", "name": " Save", "title": "Save",
            "label": "save", "value": True}), "Save")
        self.assertEqual(result["tree"]["title"], "Save")
        for field in ("name", "label", "value"):
            self.assertRegex(result["tree"][field], TOKEN_PATTERN)
        self.assertRegex(result["app"], TOKEN_PATTERN)

    def test_foreign_malformed_and_duplicate_refs_fail_closed(self):
        for ref in ("@s456:e1", "@e1", "@s123:e0", "@s123:e1\n", "secret@example.com"):
            with self.subTest(ref=ref), self.assertRaises(PrivacyError):
                SnapshotProjector().project(snapshot({"role": "button", "ref_id": ref}), "app")
        with self.assertRaises(PrivacyError):
            SnapshotProjector().project(snapshot({"role": "window", "children": [
                {"role": "button", "ref_id": "@s123:e1"},
                {"role": "button", "ref_id": "@s123:e1"},
            ]}), "app")

    def test_malformed_and_oversized_observations_fail_closed(self):
        for tree in (None, [], {"role": 7}, {"role": "window", "children": "private secret"},
                     {"role": "window", "states": [True]},
                     {"role": "window", "available_actions": {"Click": True}}):
            raw = snapshot()
            raw["data"]["tree"] = tree
            with self.subTest(tree=tree), self.assertRaises(PrivacyError):
                SnapshotProjector().project(raw, "app")
        too_many = snapshot({"role": "window", "children": [{"role": "button"} for _ in range(MAX_NODES)]})
        with self.assertRaises(PrivacyError):
            SnapshotProjector().project(too_many, "app")

    def test_safe_label_configuration_is_deliberate_and_bounded(self):
        for labels in ("Save", [""], ["x" * 81], [1], ["<PRIVATE:1>"], ["Save"] * 129):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                SnapshotProjector(labels)


class JsonLimitTests(unittest.TestCase):
    def test_deep_cyclic_non_json_and_nonfinite_objects_are_rejected(self):
        cyclic = []
        cyclic.append(cyclic)
        deep = []
        for _ in range(40):
            deep = [deep]
        for raw in (cyclic, deep, object(), {1: "invalid key"}, float("nan"), float("inf"),
                    "x" * (MAX_STRING_LENGTH + 1), 2**200):
            with self.subTest(kind=type(raw)), self.assertRaises(PrivacyError):
                validate_json(raw)

    def test_total_encoded_size_is_bounded(self):
        with self.assertRaises(PrivacyError):
            validate_json(["é" * 1000], max_bytes=1000)


if __name__ == "__main__":
    unittest.main()
