from app.cli_ops import summarize_profiles


def test_summarize_profiles_marks_balancer() -> None:
    payload = [
        {
            "remarks": "NL Pool",
            "outbounds": [
                {"protocol": "vless", "tag": "bal-nl-vless", "settings": {"address": "n1"}},
                {"protocol": "freedom", "tag": "direct"},
            ],
            "routing": {
                "balancers": [
                    {
                        "tag": "balancer",
                        "selector": ["bal-nl-"],
                        "strategy": {"type": "roundRobin"},
                        "fallbackTag": "bal-nl-vless",
                    }
                ]
            },
        },
        {
            "remarks": "Extra",
            "outbounds": [{"protocol": "vless", "tag": "proxy", "settings": {"address": "n2"}}],
        },
    ]
    rows = summarize_profiles(payload)
    assert rows[0]["kind"] == "пул"
    assert rows[0]["proxies"] == 1
    assert rows[0]["fallback"] == "bal-nl-vless"
    assert rows[1]["kind"] == "сервер"
    assert rows[1]["remarks"] == "Extra"
