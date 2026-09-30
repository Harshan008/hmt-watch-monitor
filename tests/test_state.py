from src.state import TargetState, load_state, save_state


def test_roundtrip_and_write_only_on_change(tmp_path):
    path = tmp_path / "state.json"
    states = {"a": TargetState(last_status="OUT_OF_STOCK"), "gone": TargetState()}
    assert save_state(path, states, keep_ids=["a"]) is True
    assert save_state(path, states, keep_ids=["a"]) is False  # unchanged -> no write
    loaded = load_state(path)
    assert set(loaded) == {"a"}  # removed targets are pruned
    assert loaded["a"].last_status == "OUT_OF_STOCK"
    loaded["a"].last_status = "IN_STOCK"
    assert save_state(path, loaded, keep_ids=["a"]) is True


def test_missing_or_corrupt_state_starts_fresh(tmp_path):
    assert load_state(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_state(bad) == {}


def test_unknown_fields_are_ignored(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"a": {"last_status": "OUT_OF_STOCK", "legacy": 1}}')
    assert load_state(p)["a"].last_status == "OUT_OF_STOCK"
