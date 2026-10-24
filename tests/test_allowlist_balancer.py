import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from app.config import Settings
from app.db.database import Database
from app.db.repository import SettingsRepository
from app.features.allowlist_balancer import (
    DEFAULT_PROBE_URL, ENTER_B, ENTER_GUARD, GUARD_A, InvalidPool, POOL_A,
    POOL_B, PROFILE_NAME, TO_B, UNAVAILABLE, DESCRIPTION, compose_allowlist_balancer,
    validate_allowlist_profile,
    format_profile_name, normalize_profile_name, normalize_profile_flag,
)
from app.services.feature_settings import (
    ALLOWLIST_BALANCER_KEY, normalize_feature_switch, resolve_allowlist_balancer,
    ALLOWLIST_BALANCER_NAME_KEY, ALLOWLIST_BALANCER_FLAG_KEY,
    resolve_allowlist_name, resolve_allowlist_flag,
)
from app.services.mode import TRANSFORM_MODE_KEY, VALID_TRANSFORM_MODES
from app.services.transform_service import TransformService
from app.transformers.ios_fix import apply_ios_fix, apply_ios_fix_dns

FIXTURE = Path(__file__).parent / "fixtures" / "priority_pools_3xui.json"


@pytest.fixture
def pools():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_composes_panel_pair_preserving_all_connection_fields(pools):
    original = copy.deepcopy(pools)
    result = compose_allowlist_balancer(pools)
    assert len(result) == 1
    config = result[0]
    assert config["remarks"] == PROFILE_NAME
    validate_allowlist_profile(config)
    real = [o for o in config["outbounds"] if o["protocol"] == "vless" and o["tag"] != DESCRIPTION]
    expected = [o for p in pools for o in p["outbounds"] if o["protocol"] == "vless"]
    assert real == expected
    assert len(real) == 5
    for key in ("dns", "inbounds", "policy", "stats", "log"):
        assert config[key] == pools[0][key]
    assert config["routing"]["rules"][3:5] == pools[0]["routing"]["rules"][:2]
    assert config["routing"]["rules"][-1]["balancerTag"] == POOL_A
    assert config["outbounds"][0]["tag"] == DESCRIPTION
    assert config["outbounds"][1]["tag"] == UNAVAILABLE
    assert config["observatory"] == {
        "subjectSelector": ["bal-12-", "bal-13-"], "probeUrl": DEFAULT_PROBE_URL,
        "probeInterval": "20s", "enableConcurrency": True,
    }
    assert "burstObservatory" not in config
    assert pools == original


@pytest.mark.parametrize("a", ["[A] Normal", "[А] Normal", "normal [a]", "[а]", " [A][A] "])
@pytest.mark.parametrize("b", ["[B] Reserve", "[В] Reserve", "reserve [b]", "[в]"])
def test_role_markers_allow_case_and_cyrillic(pools, a, b):
    pools[0]["remarks"], pools[1]["remarks"] = a, b
    assert len(compose_allowlist_balancer(pools)) == 1


@pytest.mark.parametrize("kind", ["none", "missing-a", "missing-b", "duplicate-a", "duplicate-b", "both", "proxy", "not-token"])
def test_missing_or_ambiguous_pairs_stay_separate(pools, kind, caplog):
    if kind == "none":
        pools[0]["remarks"], pools[1]["remarks"] = "Normal", "Reserve"
    elif kind.startswith("missing-"):
        pools.pop(0 if kind == "missing-a" else 1)
    elif kind.startswith("duplicate-"):
        pools.append(copy.deepcopy(pools[0 if kind == "duplicate-a" else 1]))
    elif kind == "both":
        pools[0]["remarks"] = "[A] [B] Wrong"
    elif kind == "proxy":
        pools[0]["routing"].pop("balancers")
    else:
        pools[0]["remarks"] = "[AAA] Normal"
    original = copy.deepcopy(pools)
    assert compose_allowlist_balancer(pools) == original
    assert pools == original
    if kind != "none":
        assert "skipped" in caplog.text


@pytest.mark.parametrize("kind", [
    "empty", "bad-selector", "system-selector", "loopback", "duplicate-tag",
    "same-node", "same-node-in-pool", "overlap", "dns-conflict", "policy-conflict",
    "inbound-conflict", "rules-conflict", "system-conflict", "reserved",
    "missing-fallback", "unknown-strategy", "chain", "missing-settings",
    "extra-proxy", "multi-balancer", "dangling-rule", "direct-member-rule", "script",
])
def test_unsupported_profiles_are_not_partially_composed(pools, kind, caplog):
    a, b = pools
    if kind == "empty":
        a["routing"]["balancers"][0]["selector"] = ["absent-"]
    elif kind == "bad-selector":
        a["routing"]["balancers"][0]["selector"] = [""]
    elif kind == "system-selector":
        a["routing"]["balancers"][0]["selector"] = ["direct"]
    elif kind == "loopback":
        a["outbounds"][0]["protocol"] = "loopback"
    elif kind == "duplicate-tag":
        b["outbounds"][1]["tag"] = b["outbounds"][0]["tag"]
    elif kind in {"same-node", "same-node-in-pool"}:
        target = b["outbounds"][0] if kind == "same-node" else a["outbounds"][1]
        target.update({k: copy.deepcopy(a["outbounds"][0][k]) for k in ("protocol", "settings", "streamSettings")})
    elif kind == "overlap":
        a["routing"]["balancers"][0]["selector"] = ["bal-"]
    elif kind == "dns-conflict":
        b["dns"]["servers"] = ["1.1.1.1"]
    elif kind == "policy-conflict":
        b["policy"] = {}
    elif kind == "inbound-conflict":
        b["inbounds"][0]["port"] = 10800
    elif kind == "rules-conflict":
        b["routing"]["rules"].pop(0)
    elif kind == "system-conflict":
        b["outbounds"][-2]["settings"] = {"domainStrategy": "UseIP"}
    elif kind == "reserved":
        a["outbounds"][-1]["tag"] = "cf-to-pool-b"
    elif kind == "missing-fallback":
        a["routing"]["balancers"][0]["fallbackTag"] = "absent"
    elif kind == "unknown-strategy":
        a["routing"]["balancers"][0]["strategy"] = {"type": "mystery"}
    elif kind == "chain":
        a["outbounds"][0]["streamSettings"]["sockopt"] = {"dialerProxy": "direct"}
    elif kind == "missing-settings":
        a["outbounds"][0].pop("settings")
    elif kind == "extra-proxy":
        a["outbounds"].append({"tag": "extra", "protocol": "vless", "settings": {}})
    elif kind == "multi-balancer":
        a["routing"]["balancers"].append({"tag": "other", "selector": ["bal-"]})
    elif kind == "dangling-rule":
        a["routing"]["rules"][0]["outboundTag"] = "absent"
    elif kind == "direct-member-rule":
        a["routing"]["rules"][0]["outboundTag"] = a["outbounds"][0]["tag"]
    else:
        a["routing"]["script"] = "custom.lua"
    original = copy.deepcopy(pools)
    assert compose_allowlist_balancer(pools) == original
    assert pools == original
    assert "skipped" in caplog.text


def test_preserves_unrelated_profiles_and_original_order(pools):
    extra = {"remarks": "Manual", "outbounds": [{"protocol": "socks", "tag": "proxy"}]}
    result = compose_allowlist_balancer([extra, pools[1], extra, pools[0], extra])
    assert [p["remarks"] for p in result] == ["Manual", PROFILE_NAME, "Manual", "Manual"]


@pytest.mark.parametrize("strategy", ["leastPing", "leastLoad", "roundRobin", "random"])
def test_source_strategy_does_not_change_priority_policy(pools, strategy):
    for p in pools:
        p["routing"]["balancers"][0]["strategy"] = {"type": strategy, "settings": {"costs": []}}
    config = compose_allowlist_balancer(pools)[0]
    assert [b["strategy"]["type"] for b in config["routing"]["balancers"]] == ["leastPing", "roundRobin", "leastPing"]


@pytest.mark.parametrize("fix", [apply_ios_fix, apply_ios_fix_dns])
def test_ios_modes_preserve_graph_dns_and_idempotency(pools, fix):
    config = compose_allowlist_balancer(pools)[0]
    fixed = fix(config)
    validate_allowlist_profile(fixed)
    assert fixed["routing"] == config["routing"]
    assert fixed["observatory"] == config["observatory"]
    assert fixed["outbounds"][0] == config["outbounds"][0]
    assert fixed["inbounds"][0]["protocol"] == "socks"
    assert fixed["inbounds"][0]["tag"] == "socks"
    assert "fakedns" not in fixed["inbounds"][0]["sniffing"]["destOverride"]
    assert fix(fixed) == fixed
    assert compose_allowlist_balancer([fixed]) == [fixed]
    assert compose_allowlist_balancer(fixed) == fixed
    assert [r.get("inboundTag") for r in fixed["routing"]["rules"][:2]] == [[ENTER_GUARD], [ENTER_B]]
    assert fixed["routing"]["rules"][2] == {"type": "field", "port": 53, "network": "tcp,udp", "balancerTag": POOL_A}
    assert sum(r.get("port") in (53, "53") for r in fixed["routing"]["rules"]) == 1


@pytest.mark.parametrize("kind", ["fallback", "dns-order", "observer", "loopback", "overlap"])
def test_damaged_composed_graph_is_rejected(pools, kind):
    config = compose_allowlist_balancer(pools)[0]
    if kind == "fallback":
        config["routing"]["balancers"][1].pop("fallbackTag")
    elif kind == "dns-order":
        config["routing"]["rules"].insert(0, config["routing"]["rules"].pop(2))
    elif kind == "observer":
        config["observatory"]["subjectSelector"] = ["bal-12-"]
    elif kind == "loopback":
        next(o for o in config["outbounds"] if o["tag"] == TO_B)["settings"]["inboundTag"] = ENTER_GUARD
    else:
        config["routing"]["balancers"][2]["selector"] = ["bal-12-"]
    for fn in (validate_allowlist_profile, apply_ios_fix, apply_ios_fix_dns, compose_allowlist_balancer):
        with pytest.raises(InvalidPool):
            fn(config)


def test_description_is_static_and_not_a_real_node(pools):
    from app.cli_ops import summarize_profiles
    config = compose_allowlist_balancer(pools)[0]
    display = config["outbounds"][0]
    assert display["protocol"] == "vless"
    assert display["settings"]["vnext"][0]["address"] == "127.0.0.1"
    assert display["settings"]["vnext"][0]["port"] == 9
    assert display["streamSettings"]["network"] == "ws"
    assert display["streamSettings"]["security"] == "tls"
    assert display["streamSettings"]["sockopt"] == {"domainStrategy": "AsIs", "dialerProxy": UNAVAILABLE}
    assert display["mux"] == {"enabled": False}
    assert summarize_profiles(config)[0]["proxies"] == 5
    # A change to a real endpoint must not be copied into the display outbound.
    pools[0]["outbounds"][0]["settings"]["vnext"][0]["address"] = "changed.example"
    assert compose_allowlist_balancer(pools)[0]["outbounds"][0] == display


@pytest.mark.parametrize("kind", [
    "address", "port", "dns", "dialer", "missing-dialer", "mux", "tls", "ws",
    "extra-field", "rule", "pool", "observer", "default-order", "other-chain",
])
def test_description_cannot_weaken_graph(pools, kind):
    config = compose_allowlist_balancer(pools)[0]
    display = config["outbounds"][0]
    if kind == "address":
        display["settings"]["vnext"][0]["address"] = "external.example"
    elif kind == "port":
        display["settings"]["vnext"][0]["port"] = 443
    elif kind == "dns":
        display["streamSettings"]["sockopt"]["domainStrategy"] = "UseIP"
    elif kind == "dialer":
        display["streamSettings"]["sockopt"]["dialerProxy"] = "direct"
    elif kind == "missing-dialer":
        display["streamSettings"]["sockopt"].pop("dialerProxy")
    elif kind == "mux":
        display["mux"]["enabled"] = True
    elif kind == "tls":
        display["streamSettings"]["tlsSettings"]["allowInsecure"] = True
    elif kind == "ws":
        display["streamSettings"]["wsSettings"]["path"] = "/different"
    elif kind == "extra-field":
        display["proxySettings"] = {"tag": "direct"}
    elif kind == "rule":
        config["routing"]["rules"].append({"type": "field", "network": "tcp,udp", "outboundTag": DESCRIPTION})
    elif kind == "pool":
        for balancer in config["routing"]["balancers"][:2]:
            balancer["selector"].append(DESCRIPTION)
    elif kind == "observer":
        config["observatory"]["subjectSelector"].append(DESCRIPTION)
    elif kind == "default-order":
        config["outbounds"][0], config["outbounds"][1] = config["outbounds"][1], config["outbounds"][0]
    elif kind == "other-chain":
        config["outbounds"][2]["streamSettings"]["sockopt"] = {"dialerProxy": "direct"}
    for fn in (validate_allowlist_profile, apply_ios_fix, apply_ios_fix_dns, compose_allowlist_balancer):
        with pytest.raises(InvalidPool):
            fn(config)


@pytest.mark.parametrize("fix", [apply_ios_fix, apply_ios_fix_dns])
def test_legacy_blackhole_first_profile_is_still_supported(pools, fix):
    config = compose_allowlist_balancer(pools)[0]
    config["outbounds"].pop(0)
    validate_allowlist_profile(config)
    fixed = fix(config)
    assert fixed["outbounds"][0]["tag"] == UNAVAILABLE
    assert compose_allowlist_balancer(fixed) == fixed


def test_existing_dns_rules_do_not_duplicate_or_prevent_required_route(pools):
    for p in pools:
        p["routing"]["rules"].insert(0, {"type": "field", "port": "53", "network": "tcp,udp", "balancerTag": "balancer"})
        p["routing"]["rules"].insert(1, {"type": "field", "port": 53, "inboundTag": ["http"], "outboundTag": "direct"})
    config = compose_allowlist_balancer(pools)[0]
    assert len([r for r in config["routing"]["rules"] if r.get("port") in (53, "53")]) == 2
    assert config["routing"]["rules"][2]["balancerTag"] == POOL_A


@pytest.mark.parametrize("mode", ["ios-fix", "ios-fix-dns", "passthrough", "ios-fix-beta"])
def test_feature_switch_is_independent_and_dynamic(pools, tmp_path, mode):
    settings = Settings(db_path=str(tmp_path / "flags.db"), transform_mode=mode, allowlist_balancer_enabled=False)
    repo = SettingsRepository(Database(settings.db_path))
    service = TransformService(settings)
    assert len(service.transform("test", pools)) == 2
    repo.set_setting(ALLOWLIST_BALANCER_KEY, "true")
    result = service.transform("test", pools)
    assert len(result) == 1
    validate_allowlist_profile(result[0])
    assert result[0]["inbounds"][0]["tag"] == ("mixed" if mode == "passthrough" else "socks")
    repo.set_setting(ALLOWLIST_BALANCER_KEY, "false")
    assert len(service.transform("test", pools)) == 2
    assert repo.get_setting(TRANSFORM_MODE_KEY) is None
    assert VALID_TRANSFORM_MODES == {"passthrough", "ios-fix", "ios-fix-dns"}


@pytest.mark.parametrize("value,expected", [("on", True), ("TRUE", True), ("1", True), ("off", False), ("false", False), ("0", False)])
def test_feature_switch_values(value, expected):
    assert normalize_feature_switch(value) is expected
    assert resolve_allowlist_balancer(Settings(), value) is expected


def test_invalid_feature_switch_disables_composition():
    assert resolve_allowlist_balancer(Settings(), "typo") is False
    with pytest.raises(ValueError):
        normalize_feature_switch("typo")


@pytest.mark.parametrize("url", ["http://probe.example", "https://", "https://u:p@probe.example", "https://probe.example/#x", "https://probe.example:99999"])
def test_invalid_probe_configuration(url):
    with pytest.raises(ValidationError):
        Settings(allowlist_probe_url=url)


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("nan"), 3601])
def test_invalid_probe_interval(interval):
    with pytest.raises(ValidationError):
        Settings(allowlist_probe_interval_sec=interval)


def test_custom_probe_settings_reach_generated_profile(pools, tmp_path):
    service = TransformService(Settings(db_path=str(tmp_path / "probe.db"), allowlist_probe_url="https://probe.example/204", allowlist_probe_interval_sec=30))
    result = service.transform("test", pools)[0]
    assert result["observatory"]["probeUrl"] == "https://probe.example/204"
    assert result["observatory"]["probeInterval"] == "30s"


def test_panel_id_changes_do_not_change_role_selection(pools):
    for p, previous, replacement in zip(pools, ("bal-12-", "bal-13-"), ("bal-901-", "bal-4-")):
        for ob in p["outbounds"]:
            ob["tag"] = ob["tag"].replace(previous, replacement)
        balancer = p["routing"]["balancers"][0]
        balancer["selector"] = [replacement]
        balancer["fallbackTag"] = balancer["fallbackTag"].replace(previous, replacement)
    result = compose_allowlist_balancer(pools)[0]
    assert result["routing"]["balancers"][0]["selector"] == ["bal-901-"]
    assert result["routing"]["balancers"][2]["selector"] == ["bal-4-"]


def test_expired_info_profile_and_single_object_stay_unchanged():
    config = {"remarks": "Subscription expired", "outbounds": [{"protocol": "socks", "tag": "proxy", "settings": {}}]}
    assert compose_allowlist_balancer(config) == config
    assert compose_allowlist_balancer([config]) == [config]


def test_marks_inside_member_fields_do_not_define_profile_role(pools):
    pools[0]["remarks"] = "Normal"
    pools[0]["outbounds"][0]["settings"]["remarks"] = "[A]"
    assert len(compose_allowlist_balancer(pools)) == 2


@pytest.mark.parametrize("value", [[], [1], {}, 1, None])
def test_malformed_selector_stays_separate(pools, value):
    pools[0]["routing"]["balancers"][0]["selector"] = value
    assert compose_allowlist_balancer(pools) == pools


def test_malformed_fallback_and_rule_target_stay_separate(pools):
    pools[0]["routing"]["balancers"][0]["fallbackTag"] = ["bad"]
    assert compose_allowlist_balancer(pools) == pools
    pools[0]["routing"]["balancers"][0].pop("fallbackTag")
    pools[0]["routing"]["rules"][0]["outboundTag"] = ["bad"]
    assert compose_allowlist_balancer(pools) == pools


@pytest.mark.parametrize("value", [None, [], {}])
def test_malformed_member_protocol_stays_separate(pools, value):
    pools[0]["outbounds"][0]["protocol"] = value
    assert compose_allowlist_balancer(pools) == pools


def test_cli_feature_toggle_keeps_transform_mode(tmp_path, monkeypatch):
    import app.cli as cli
    repo = SettingsRepository(Database(tmp_path / "cli.db"))
    repo.set_setting(TRANSFORM_MODE_KEY, "ios-fix-dns")
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    runner = CliRunner()
    assert runner.invoke(cli.app, ["settings", "allowlist-balancer", "off"]).exit_code == 0
    assert repo.get_setting(ALLOWLIST_BALANCER_KEY) == "false"
    assert runner.invoke(cli.app, ["settings", "allowlist-balancer", "on"]).exit_code == 0
    assert repo.get_setting(ALLOWLIST_BALANCER_KEY) == "true"
    assert repo.get_setting(TRANSFORM_MODE_KEY) == "ios-fix-dns"
    assert runner.invoke(cli.app, ["settings", "allowlist-balancer", "typo"]).exit_code == 1


@pytest.mark.parametrize("mode", ["ios-fix", "ios-fix-dns"])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_http_subscription_composes_pair_and_preserves_metadata(pools, tmp_path, monkeypatch, mode, method):
    from app.main import app
    settings = Settings(db_path=str(tmp_path / "http.db"), transform_mode=mode)
    monkeypatch.setattr(app.state, "settings", settings)
    monkeypatch.setattr(app.state, "transform_service", TransformService(settings))
    response = httpx.Response(200, json=pools, headers={
        "Content-Type": "text/plain", "Subscription-Userinfo": "upload=1; download=2",
        "ProviderID": "test-provider", "DNS-From-JSON-Enable": "true", "X-Hwid-Active": "true",
    })
    upstream = AsyncMock()
    upstream.get.return_value = response
    upstream.__aenter__.return_value = upstream
    with patch("app.services.upstream.httpx.AsyncClient", return_value=upstream):
        result = TestClient(app).request(method, "/json/abcd1234efgh5678", headers={"X-HWID": "dummy"})
    assert result.status_code == 200
    assert result.headers["providerid"] == "test-provider"
    assert result.headers["dns-from-json-enable"] == "true"
    assert result.headers["x-hwid-active"] == "true"
    assert result.headers["cache-control"] == "no-store"
    assert upstream.get.call_args.kwargs["headers"]["x-hwid"] == "dummy"
    if method == "GET":
        assert len(result.json()) == 1
        validate_allowlist_profile(result.json()[0])
    else:
        assert result.content == b""


def test_hwid_denial_headers_survive_without_transform(tmp_path, monkeypatch):
    from app.main import app
    settings = Settings(db_path=str(tmp_path / "denied.db"))
    service = TransformService(settings)
    monkeypatch.setattr(app.state, "settings", settings)
    monkeypatch.setattr(app.state, "transform_service", service)
    upstream = AsyncMock()
    upstream.get.return_value = httpx.Response(404, headers={
        "X-Hwid-Active": "true", "X-Hwid-Max-Devices-Reached": "true",
    })
    upstream.__aenter__.return_value = upstream
    with patch("app.services.upstream.httpx.AsyncClient", return_value=upstream), patch.object(service, "transform") as transform:
        result = TestClient(app).get("/json/abcd1234efgh5678")
    assert result.status_code == 404
    assert result.headers["x-hwid-max-devices-reached"] == "true"
    assert result.content == b""
    transform.assert_not_called()


def test_base64_with_marker_text_is_never_composed(tmp_path, monkeypatch):
    from app.main import app
    settings = Settings(db_path=str(tmp_path / "base64.db"))
    service = TransformService(settings)
    monkeypatch.setattr(app.state, "settings", settings)
    monkeypatch.setattr(app.state, "transform_service", service)
    upstream = AsyncMock()
    text = "vless://dummy@example.com:443#[A]\nvless://dummy@example.org:443#[B]"
    upstream.get.return_value = httpx.Response(200, text=text)
    upstream.__aenter__.return_value = upstream
    with patch("app.services.upstream.httpx.AsyncClient", return_value=upstream), patch.object(service, "transform") as transform:
        result = TestClient(app).get("/json/abcd1234efgh5678")
    assert result.status_code == 200
    assert result.text == text
    transform.assert_not_called()


@pytest.mark.parametrize("code,expected", [
    ("RU", "🇷🇺 Мой VPN"), (" nl ", "🇳🇱 Мой VPN"), ("de", "🇩🇪 Мой VPN"),
    ("EU", "🇪🇺 Мой VPN"), ("", "Мой VPN"), ("off", "Мой VPN"),
])
def test_profile_name_and_flag_are_display_settings(pools, code, expected):
    result = compose_allowlist_balancer(pools, profile_name=" Мой VPN ", flag_code=code)
    assert result[0]["remarks"] == expected
    baseline = compose_allowlist_balancer(pools)[0]
    assert result[0]["routing"] == baseline["routing"]
    assert result[0]["outbounds"] == baseline["outbounds"]
    assert apply_ios_fix(result)[0]["remarks"] == expected
    assert apply_ios_fix_dns(result)[0]["remarks"] == expected
    assert compose_allowlist_balancer(result) == result
    assert pools[0]["remarks"].startswith("[A]")


@pytest.mark.parametrize("name", ["", " ", "bad\nname", "bad\x00name", "[A] VPN", "VPN [в]"])
def test_invalid_profile_names_are_rejected(name):
    with pytest.raises(ValueError):
        normalize_profile_name(name)
    with pytest.raises(ValidationError):
        Settings(allowlist_balancer_name=name)


@pytest.mark.parametrize("code", ["R", "RUS", "12", "РФ", "ß", "🇷🇺", "R\nU"])
def test_invalid_flag_codes_are_rejected(code):
    with pytest.raises(ValueError):
        normalize_profile_flag(code)
    with pytest.raises(ValidationError):
        Settings(allowlist_balancer_flag=code)


def test_name_and_flag_from_env(monkeypatch):
    monkeypatch.setenv("ALLOWLIST_BALANCER_NAME", "Мой VPN")
    monkeypatch.setenv("ALLOWLIST_BALANCER_FLAG", "ru")
    settings = Settings(_env_file=None)
    assert settings.allowlist_balancer_name == "Мой VPN"
    assert settings.allowlist_balancer_flag == "RU"


@pytest.mark.parametrize("mode", ["ios-fix", "ios-fix-dns", "passthrough"])
def test_profile_label_database_override_is_dynamic(pools, tmp_path, mode):
    settings = Settings(db_path=str(tmp_path / "label.db"), transform_mode=mode,
                        allowlist_balancer_name="Из env", allowlist_balancer_flag="NL")
    service = TransformService(settings)
    repo = SettingsRepository(Database(settings.db_path))
    assert service.transform("sub", pools)[0]["remarks"] == "🇳🇱 Из env"
    repo.set_setting(ALLOWLIST_BALANCER_NAME_KEY, "Новое имя")
    repo.set_setting(ALLOWLIST_BALANCER_FLAG_KEY, "RU")
    assert service.transform("sub", pools)[0]["remarks"] == "🇷🇺 Новое имя"
    repo.set_setting(ALLOWLIST_BALANCER_FLAG_KEY, "")
    assert service.transform("sub", pools)[0]["remarks"] == "Новое имя"
    assert repo.get_setting(TRANSFORM_MODE_KEY) is None
    assert repo.get_setting(ALLOWLIST_BALANCER_KEY) is None


def test_invalid_database_label_uses_valid_env_defaults():
    settings = Settings(allowlist_balancer_name="Default", allowlist_balancer_flag="DE")
    assert resolve_allowlist_name(settings, None) == "Default"
    assert resolve_allowlist_name(settings, "[B] wrong") == "Default"
    assert resolve_allowlist_flag(settings, None) == "DE"
    assert resolve_allowlist_flag(settings, "wrong") == "DE"
    assert resolve_allowlist_flag(settings, "") == ""
    assert format_profile_name("Name", "off") == "Name"


def test_cli_name_and_flag_settings_are_independent(tmp_path, monkeypatch):
    import app.cli as cli
    repo = SettingsRepository(Database(tmp_path / "label-cli.db"))
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    repo.set_setting(ALLOWLIST_BALANCER_KEY, "false")
    repo.set_setting(TRANSFORM_MODE_KEY, "ios-fix-dns")
    runner = CliRunner()
    assert runner.invoke(cli.app, ["settings", "allowlist-balancer-name", "Мой VPN"]).exit_code == 0
    assert runner.invoke(cli.app, ["settings", "allowlist-balancer-flag", "ru"]).exit_code == 0
    assert repo.get_setting(ALLOWLIST_BALANCER_NAME_KEY) == "Мой VPN"
    assert repo.get_setting(ALLOWLIST_BALANCER_FLAG_KEY) == "RU"
    assert runner.invoke(cli.app, ["settings", "allowlist-balancer-flag", "off"]).exit_code == 0
    assert repo.get_setting(ALLOWLIST_BALANCER_FLAG_KEY) == ""
    assert runner.invoke(cli.app, ["settings", "allowlist-balancer-flag", "RUS"]).exit_code == 1
    assert runner.invoke(cli.app, ["settings", "allowlist-balancer-name", "[A] Wrong"]).exit_code == 1
    assert repo.get_setting(ALLOWLIST_BALANCER_NAME_KEY) == "Мой VPN"
    assert repo.get_setting(TRANSFORM_MODE_KEY) == "ios-fix-dns"
    assert repo.get_setting(ALLOWLIST_BALANCER_KEY) == "false"


@pytest.mark.parametrize("choice,value,key,expected", [
    ("4", "Мой VPN", ALLOWLIST_BALANCER_NAME_KEY, "Мой VPN"),
    ("5", "ru", ALLOWLIST_BALANCER_FLAG_KEY, "RU"),
])
def test_interactive_name_and_flag_settings(tmp_path, monkeypatch, choice, value, key, expected):
    import app.cli as cli
    repo = SettingsRepository(Database(tmp_path / "menu.db"))
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    choices = iter([choice, "0"])
    monkeypatch.setattr(cli, "prompt_line", lambda *args: next(choices))
    monkeypatch.setattr(cli, "text_prompt", lambda *args, **kwargs: value)
    cli._run_settings_menu()
    assert repo.get_setting(key) == expected
