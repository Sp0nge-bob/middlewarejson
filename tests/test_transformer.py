import json
from pathlib import Path

from app.services.transformer import PassthroughTransformer

FIXTURE = Path(__file__).parent / "fixtures" / "sample_sub.json"


def test_passthrough_does_not_modify_payload() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transformer = PassthroughTransformer()
    assert transformer.transform(payload) == payload