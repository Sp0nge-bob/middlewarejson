import os

# Фиксированный путь для тестов — не зависит от локального .env
os.environ["UPSTREAM_JSON_PATH"] = "/json"
os.environ["AGENT_JSON_PATH"] = "/json"