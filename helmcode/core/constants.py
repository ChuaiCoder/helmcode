from __future__ import annotations

APP_NAME = "helmcode"
DEFAULT_PERMISSION_MODE = "suggest"
DEFAULT_READ_LIMIT = 20_000
SESSION_DIR_NAME = ".helmcode"
PENDING_PATCH_FILE = "pending.patch"
SESSION_DB_FILE = "sessions.sqlite3"

MODEL_ROLE_DEFAULT = "default"
MODEL_ROLE_FAST = "fast"
MODEL_ROLE_PLANNING = "planning"
MODEL_ROLE_CODING = "coding"
MODEL_ROLE_REVIEW = "review"

MODEL_ROLES = {
    MODEL_ROLE_DEFAULT,
    MODEL_ROLE_FAST,
    MODEL_ROLE_PLANNING,
    MODEL_ROLE_CODING,
    MODEL_ROLE_REVIEW,
}
