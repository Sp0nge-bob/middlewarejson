"""Offline test runner; never loads source .env or uses production services."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / '.env').exists():
    raise SystemExit('Use an isolated checkout without .env')
env = os.environ.copy()
env.update(UPSTREAM_BASE_URL="https://upstream.invalid", UPSTREAM_JSON_PATH="/json",
           AGENT_JSON_PATH="/json", DB_PATH=str(ROOT / ".test_tmp" / "isolated-settings.db"),
           TRANSFORM_MODE="ios-fix", ALLOWLIST_BALANCER_ENABLED="true",
           PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
env.pop("XRAY_TEST_BINARY", None)
env["PYTHONPATH"] = str(ROOT / "scripts") + os.pathsep + str(ROOT)
command = [sys.executable, "-m", "pytest", "-p", "offline_harness", "-p", "no:cacheprovider", "-q", *(sys.argv[1:] or ["tests"])]
try:
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=30)
except subprocess.TimeoutExpired as exc:
    sys.stdout.buffer.write((exc.stdout or b"") + (exc.stderr or b""))
    print("\nTIMEOUT: test process terminated after 30 seconds")
    raise SystemExit(124)
sys.stdout.buffer.write(result.stdout + result.stderr)
raise SystemExit(result.returncode)
