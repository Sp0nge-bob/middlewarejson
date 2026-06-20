from app.services.panel_api import parse_group_members, parse_group_names


def test_parse_group_names_from_objects() -> None:
    groups = [
        {"name": "premium", "count": 2},
        {"groupName": "basic", "memberCount": 1},
    ]
    assert parse_group_names(groups) == ["premium", "basic"]


def test_parse_group_names_from_strings() -> None:
    assert parse_group_names(["premium", "basic"]) == ["premium", "basic"]


def test_parse_group_members_from_strings() -> None:
    members = parse_group_members(["a@example.com", "b@example.com"])
    assert members == [{"email": "a@example.com"}, {"email": "b@example.com"}]


def test_parse_group_members_from_objects() -> None:
    members = parse_group_members(
        [{"email": "a@example.com", "subId": "sub_a", "enable": True}]
    )
    assert members[0]["subId"] == "sub_a"