"""Shared fixtures for warikan-bot tests.

Stubs external dependencies (firebase, linebot, openai) before any src imports
so module-level calls like firestore.client() and SecretParam().value don't fail.
"""

from unittest.mock import MagicMock
import sys

# ── Firebase stubs ──────────────────────────────────────

_firebase_admin = MagicMock()
_firebase_admin.firestore.SERVER_TIMESTAMP = "SERVER_TIMESTAMP"
_firebase_admin.firestore.Query.DESCENDING = "DESCENDING"
sys.modules["firebase_admin"] = _firebase_admin
sys.modules["firebase_admin.firestore"] = _firebase_admin.firestore

_firebase_functions = MagicMock()
# Make SecretParam("X").value return a dummy string
_firebase_functions.params.SecretParam.return_value.value = "dummy_secret"
sys.modules["firebase_functions"] = _firebase_functions
sys.modules["firebase_functions.params"] = _firebase_functions.params
sys.modules["firebase_functions.firestore_fn"] = _firebase_functions.firestore_fn
sys.modules["firebase_functions.https_fn"] = _firebase_functions.https_fn

# ── LINE SDK stubs ──────────────────────────────────────

for mod_name in [
    "linebot",
    "linebot.v3",
    "linebot.v3.messaging",
    "linebot.v3.webhooks",
    "linebot.v3.exceptions",
]:
    sys.modules[mod_name] = MagicMock()

# ── OpenAI stub ─────────────────────────────────────────

_openai = MagicMock()
sys.modules["openai"] = _openai
