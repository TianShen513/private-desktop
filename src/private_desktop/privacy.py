"""Conservative projection of desktop observations for a remote model.

Tokens are session-local pseudonyms, not encryption or anonymization. The vault
has no recovery operation: an agent cannot ask it to restore a hidden value.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
from typing import Any, Iterable


DEFAULT_SAFE_LABELS = (
    "OK", "Cancel", "Next", "Back", "Close", "Save", "Open", "Search",
    "Submit", "Continue", "Done", "Apply", "Yes", "No", "Add", "Remove",
    "Edit", "Delete", "Demo note", "Save note",
)
MAX_BACKEND_BYTES = 512 * 1024
MAX_DEPTH = 32
MAX_VALUES = 16000
MAX_STRING_LENGTH = 16384
MAX_NODES = 2048
MAX_TOKENS = 8192
REF_PATTERN = re.compile(r"@s[A-Za-z0-9]{1,63}:e[1-9][0-9]{0,7}\Z", re.ASCII)
SNAPSHOT_PATTERN = re.compile(r"s[A-Za-z0-9]{1,63}\Z", re.ASCII)
TOKEN_PATTERN = re.compile(r"<PRIVATE:[0-9a-f]{32}>\Z", re.ASCII)
_PLACEHOLDER_PATTERN = re.compile(
    r"[<\[{]\s*(?:private|redacted|secret|token|email|person|phone|address|account|password)"
    r"(?:[\s:_-]|[>\]}])", re.IGNORECASE,
)
SAFE_ROLES = frozenset("""
alert alertdialog application article banner browser button cell checkbox
colorwell column combobox complementary contentinfo datefield definition dialog
disclosure dockitem document drawer form grid group handle heading helptag image
incrementor layoutitem levelindicator link list listbox log main marquee matte
math menu menubutton menuitem navigation note option outline page paragraph popover
progressbar radiobutton radiogroup region relevanceindicator row ruler rulermarker
scrollarea scrollbar search separator sheet slider splitter statictext status
switch tab tablist tabpanel table textfield term timefield timer toolbar tooltip
treeitem webarea window unknown
""".split())
SAFE_ACTIONS = frozenset((
    "Click", "DoubleClick", "RightClick", "TripleClick", "SetValue", "SetFocus",
    "Expand", "Collapse", "Select", "Toggle", "Check", "Uncheck", "Scroll",
    "ScrollTo", "PressKey", "TypeText", "Clear", "Hover", "Drag",
))
SAFE_STATES = frozenset((
    "focused", "disabled", "secure", "expanded", "checked", "selected", "hidden",
    "busy", "modal", "required", "indeterminate", "pressed", "readonly",
    "offscreen", "invalid", "multiselectable", "haspopup",
))


class PrivacyError(ValueError):
    """An observation cannot be safely projected. Its message is always static."""


def contains_private_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER_PATTERN.search(text))


def validate_json(value: Any, *, max_bytes: int = MAX_BACKEND_BYTES) -> None:
    """Bound the entire object, including fields that the projection will omit."""
    pending = [(value, 0)]
    seen_containers: set[int] = set()
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > MAX_VALUES or depth > MAX_DEPTH:
            raise PrivacyError("Observation exceeds safety limits")
        if type(item) is dict or type(item) is list:
            if id(item) in seen_containers:
                raise PrivacyError("Invalid observation structure")
            seen_containers.add(id(item))
            if len(item) > MAX_VALUES:
                raise PrivacyError("Observation exceeds safety limits")
            if type(item) is dict:
                if any(type(key) is not str or len(key) > 256 for key in item):
                    raise PrivacyError("Invalid observation structure")
                pending.extend((child, depth + 1) for child in item.values())
            else:
                pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            if len(item) > MAX_STRING_LENGTH:
                raise PrivacyError("Observation exceeds safety limits")
        elif type(item) is int:
            if item.bit_length() > 128:
                raise PrivacyError("Observation exceeds safety limits")
        elif type(item) is float:
            if not math.isfinite(item):
                raise PrivacyError("Invalid observation structure")
        elif item is not None and type(item) is not bool:
            raise PrivacyError("Invalid observation structure")
    try:
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise PrivacyError("Invalid observation structure") from None
    if len(encoded) > max_bytes:
        raise PrivacyError("Observation exceeds safety limits")


class TokenVault:
    """Memory-only, bounded pseudonyms indexed by a session-keyed digest."""

    def __init__(self, max_tokens: int = MAX_TOKENS):
        if type(max_tokens) is not int or not 1 <= max_tokens <= MAX_TOKENS:
            raise ValueError("Invalid token limit")
        self._key = secrets.token_bytes(32)
        self._tokens: dict[bytes, str] = {}
        self._max_tokens = max_tokens

    def token(self, value: Any) -> str:
        validate_json(value)
        payload = json.dumps(
            value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        digest = hmac.new(self._key, payload, hashlib.sha256).digest()
        if digest in self._tokens:
            return self._tokens[digest]
        if len(self._tokens) >= self._max_tokens:
            raise PrivacyError("Session token limit reached")
        token = "<PRIVATE:" + secrets.token_hex(16) + ">"
        self._tokens[digest] = token
        return token


class SnapshotProjector:
    """Allow known structure, replace private values, and omit other metadata."""

    def __init__(self, safe_labels: Iterable[str] = DEFAULT_SAFE_LABELS):
        if isinstance(safe_labels, (str, bytes)):
            raise ValueError("Invalid safe label allowlist")
        labels = tuple(safe_labels)
        if len(labels) > 128 or any(
            type(label) is not str or not label or len(label) > 80
            or contains_private_placeholder(label) for label in labels
        ):
            raise ValueError("Invalid safe label allowlist")
        self.safe_labels = frozenset(labels)
        self.vault = TokenVault()

    def _private(self, value: Any, *, label: bool = False) -> str:
        if label and type(value) is str and value in self.safe_labels:
            return value
        return self.vault.token(value)

    def project(self, envelope: dict[str, Any], app: str) -> tuple[dict[str, Any], set[str]]:
        validate_json(envelope)
        data = envelope.get("data")
        if type(data) is not dict or type(data.get("complete")) is not bool:
            raise PrivacyError("Invalid snapshot response")
        snapshot_id = data.get("snapshot_id")
        if type(snapshot_id) is not str or not SNAPSHOT_PATTERN.fullmatch(snapshot_id):
            raise PrivacyError("Invalid snapshot response")
        refs: set[str] = set()
        node_count = [0]
        tree = self._node(data.get("tree"), snapshot_id, refs, node_count)
        projected = {
            "app": self._private(app),
            "snapshot_id": snapshot_id,
            "complete": data["complete"],
            "ref_count": len(refs),
            "tree": tree,
        }
        if type(data.get("truncated")) is bool:
            projected["truncated"] = data["truncated"]
        return projected, refs

    def _node(self, raw: Any, snapshot_id: str, refs: set[str], count: list[int]) -> dict[str, Any]:
        if type(raw) is not dict or type(raw.get("role")) is not str:
            raise PrivacyError("Invalid snapshot response")
        count[0] += 1
        if count[0] > MAX_NODES:
            raise PrivacyError("Snapshot exceeds safety limits")
        role = raw["role"]
        node: dict[str, Any] = {"role": role if role in SAFE_ROLES else self._private(role)}
        if "ref_id" in raw and raw["ref_id"] is not None:
            ref = raw["ref_id"]
            if type(ref) is not str or not REF_PATTERN.fullmatch(ref):
                raise PrivacyError("Invalid snapshot reference")
            if not ref.startswith("@" + snapshot_id + ":") or ref in refs:
                raise PrivacyError("Invalid snapshot reference")
            refs.add(ref)
            node["ref_id"] = ref
        for field in ("name", "title", "description", "label", "hint", "value"):
            if field in raw and raw[field] is not None:
                node[field] = self._private(raw[field], label=field != "value")
        if "available_actions" in raw:
            actions = raw["available_actions"]
            if type(actions) is not list or any(type(action) is not str for action in actions):
                raise PrivacyError("Invalid snapshot actions")
            node["available_actions"] = [
                action if action in SAFE_ACTIONS else self._private(action) for action in actions
            ]
        if "states" in raw:
            states = raw["states"]
            if type(states) is list and all(type(state) is str for state in states):
                node["states"] = {state: True for state in states if state in SAFE_STATES}
            elif type(states) is dict and all(type(value) is bool for value in states.values()):
                node["states"] = {state: value for state, value in states.items() if state in SAFE_STATES}
            else:
                raise PrivacyError("Invalid snapshot states")
        if "subtree_truncated" in raw:
            if type(raw["subtree_truncated"]) is not bool:
                raise PrivacyError("Invalid snapshot response")
            node["subtree_truncated"] = raw["subtree_truncated"]
        if "children" in raw:
            if type(raw["children"]) is not list:
                raise PrivacyError("Invalid snapshot response")
            node["children"] = [self._node(child, snapshot_id, refs, count) for child in raw["children"]]
        return node
