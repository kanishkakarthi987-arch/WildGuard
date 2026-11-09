import os
import sys
import tempfile
from pathlib import Path

# Point the app at a throwaway database BEFORE it is imported.
_tmp = tempfile.mkdtemp(prefix="wildguard-test-")
os.environ["WILDGUARD_DB"] = str(Path(_tmp) / "test.db")
os.environ["NOTIFY_PROVIDER"] = "dry_run"
os.environ["VOICE_PROVIDER"] = "dry_run"
os.environ["WILDGUARD_ADMIN_TOKEN"] = "wildguard-admin"
os.environ["WILDGUARD_GATEWAY_KEY"] = "test-gateway-key"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
