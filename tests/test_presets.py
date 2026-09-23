"""预制档案与导入/导出测试：schema 校验、三份预制文件质量、import、export 往返、启动幂等。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from replicant.db import Clone, Memory
from replicant.llm import MockLLM
from replicant.main import create_app
from replicant.persona import profile as profile_mod
from replicant.presets import FORMAT, PRESET_DIR, PresetFormatError, export_clone, import_preset, seed_presets, validate_preset

from sqlmodel import select

PRESET_FILES = sorted(PRESET_DIR.glob("*.json"))


def test_three_preset_files_exist():
    assert len(PRESET_FILES) == 3


@pytest.mark.parametrize("path", PRESET_FILES, ids=[p.stem for p in PRESET_FILES])
def test_preset_file_schema_and_richness(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == FORMAT
    p = validate_preset(data)
    assert p["name"] and p["personality_line"]
    assert 6 <= len(p["traits"]) <= 10
    assert 5 <= len(p["values"]) <= 8
    assert 8 <= len(p["facts"]) <= 15
    assert 4 <= len(p["style_samples"]) <= 6
    assert 5 <= len(p["memories"]) <= 10
    assert all(m["kind"] in {"fact", "conversation", "reflection"} for m in p["memories"])
    assert all(1 <= m["importance"] <= 10 for m in p["memories"])


def test_validate_rejects_bad_shape():
    with pytest.raises(PresetFormatError):
        validate_preset({"traits": []})
    with pytest.raises(PresetFormatError):
        validate_preset(["not-a-dict"])
    # 容错：memory kind 不在白名单被规整为 fact，importance 越界被 clamp
    data = validate_preset({"name": "X", "memories": [{"content": "c", "kind": "weird", "importance": 99}]})
    assert data["memories"] == [{"content": "c", "importance": 10, "kind": "fact"}]


def test_import_creates_clone_and_seed_memories(session, llm):
    data = validate_preset(json.loads(PRESET_FILES[0].read_text(encoding="utf-8")))
    result = import_preset(session, llm, data, source="import")
    clone = session.get(Clone, result["clone_id"])
    assert clone.name == data["name"]
    v1 = profile_mod.history(session, clone.id)[0]
    assert v1.source == "import"
    mems = session.exec(select(Memory).where(Memory.clone_id == clone.id)).all()
    assert len(mems) >= len(data["memories"])  # 种子记忆 + 可能的反思记忆
    assert result["memories_written"] == len(data["memories"])
    assert any(m.importance == 9 for m in mems)


def test_export_import_roundtrip(session, llm):
    src = import_preset(session, llm, json.loads(PRESET_FILES[0].read_text(encoding="utf-8")))
    exported = export_clone(session, src["clone_id"])
    assert exported["format"] == FORMAT

    dst = import_preset(session, llm, exported, source="import")
    # 对照导入后新克隆的 v1（反思会在其上叠加新版本，属设计行为）
    dst_v1 = profile_mod.to_dict(profile_mod.history(session, dst["clone_id"])[0])
    for key in ("name", "traits", "values", "facts", "style_samples"):
        assert exported[key] == dst_v1[key]
    # 种子记忆内容一致（【反思】前缀等规整不改变正文）
    src_mems = [m["content"] for m in exported["memories"]]
    dst_mems = [
        m["content"] for m in export_clone(session, dst["clone_id"])["memories"]
    ][: len(src_mems)]
    assert src_mems == dst_mems


def test_seed_presets_idempotent(session, llm):
    first = seed_presets(session, llm)
    assert first["loaded"] == 3 and first["skipped"] == 0
    second = seed_presets(session, llm)
    assert second == {"loaded": 0, "skipped": 3}
    assert len(session.exec(select(Clone)).all()) == 3


def test_export_endpoint_download_and_import_client():
    app = create_app(llm=MockLLM(), db_url="sqlite://", load_presets=True)
    client = TestClient(app)
    clones = client.get("/clones").json()
    assert len(clones) == 3
    assert {c["source"] for c in clones} == {"preset"}
    pid = clones[0]["id"]
    resp = client.get(f"/clones/{pid}/export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    data = resp.json()
    assert data["format"] == FORMAT and data["traits"]
    # 导出的 JSON 再导入回来可以得到同名新克隆
    r = client.post("/clones/import", json={"preset": data})
    assert r.status_code == 200 and r.json()["name"] == data["name"]
    assert len(client.get("/clones").json()) == 4
