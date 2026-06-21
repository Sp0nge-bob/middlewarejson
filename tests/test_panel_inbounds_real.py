import json
from pathlib import Path

from app.models.panel_inbound import panel_inbounds_to_descriptors

REAL_FIXTURE = Path(__file__).parent / "fixtures" / "panel_inbounds_real_11.json"


def test_real_panel_api_yields_eleven_active_endpoints() -> None:
    inbounds = json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))
    assert len(inbounds) == 11
    assert all(item.get("enable") is not False for item in inbounds)

    descriptors = panel_inbounds_to_descriptors(inbounds)
    assert len(descriptors) == 11
    assert {item.panel_inbound_id for item in descriptors} == {
        1, 2, 3, 8, 9, 12, 13, 16, 17, 21, 23,
    }

    by_id = {item.panel_inbound_id: item for item in descriptors}
    assert by_id[13].address == "mirror1.caelixflow.com"
    assert by_id[16].address == "mirror2.caelixflow.com"
    assert by_id[21].address == "1pmf5o71tc.a.trbcdn.net"