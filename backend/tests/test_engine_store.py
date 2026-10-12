"""Model store: required files, partial downloads, verification and safe pack import."""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

from app.model_store import (
    DOWNLOAD_MARKER, MANIFEST, PackImportError, ModelStore, load_catalog, sha256_file, structure_problem,
)

IT2 = "indictrans2-indic-en-200m"
GEMMA = "gemma4-e2b"


def safetensors_bytes(n_bytes: int = 16) -> bytes:
    header = json.dumps({"w": {"dtype": "F32", "shape": [n_bytes // 4], "data_offsets": [0, n_bytes]}}).encode()
    return struct.pack("<Q", len(header)) + header + b"\0" * n_bytes


def write_it2(folder: Path, code: str = "# modeling code\n") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "tokenizer_config.json", "dict.SRC.json", "dict.TGT.json", "generation_config.json"):
        (folder / name).write_text("{}")
    (folder / "model.SRC").write_bytes(b"spm-src")
    (folder / "model.TGT").write_bytes(b"spm-tgt")
    for name in ("configuration_indictrans.py", "modeling_indictrans.py", "tokenization_indictrans.py"):
        (folder / name).write_text(code)
    (folder / "model.safetensors").write_bytes(safetensors_bytes())


def write_gemma(folder: Path, model: bytes = b"GGUF\x03\x00\x00\x00" + b"\0" * 64) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "gemma-4-E2B-it-Q4_K_M.gguf").write_bytes(model)
    (folder / "mmproj-gemma-4-E2B-it-f16.gguf").write_bytes(b"GGUF\x03\x00\x00\x00" + b"\1" * 32)


@pytest.fixture()
def store(tmp_path) -> ModelStore:
    return ModelStore(tmp_path / "store")


def downloaded(store: ModelStore, model_id: str) -> Path:
    """Simulate a finished download from the pinned repo."""
    d = store.model_dir(model_id)
    (write_it2 if model_id == IT2 else write_gemma)(d)
    assert store.verify(model_id, record=True, log=lambda m: None)
    return d


# ---- catalog -------------------------------------------------------------------------------

def test_indictrans2_download_patterns_keep_the_sentencepiece_files():
    from huggingface_hub.utils import filter_repo_objects

    repo_files = [
        ".gitattributes", "README.md", "config.json", "configuration_indictrans.py", "dict.SRC.json",
        "dict.TGT.json", "generation_config.json", "model.SRC", "model.TGT", "model.safetensors",
        "modeling_indictrans.py", "pytorch_model.bin", "special_tokens_map.json",
        "tokenization_indictrans.py", "tokenizer_config.json",
    ]
    for model_id in ("indictrans2-indic-en-1b", IT2):
        entry = load_catalog()[model_id]
        kept = set(filter_repo_objects(repo_files, allow_patterns=entry.allow_patterns))
        assert {"model.SRC", "model.TGT", "dict.SRC.json", "dict.TGT.json"} <= kept
        assert "pytorch_model.bin" not in kept  # pickle: never needed, can run code
        for group in entry.required_groups():
            assert any(name in kept for name in group), group


def test_gemma_e4b_file_names_keep_their_case():
    entry = load_catalog()["gemma4-e4b"]
    assert entry.source["hf_repo"] == "unsloth/gemma-4-E4B-it-GGUF"
    assert entry.files["model"]["name"] == "gemma-4-E4B-it-Q4_K_M.gguf"


def test_indictrans2_load_peak_is_counted():
    catalog = load_catalog()
    assert catalog["indictrans2-indic-en-1b"].peak_ram_gb >= 4.5
    assert catalog[IT2].peak_ram_gb > catalog[IT2].ram_gb
    assert catalog[GEMMA].peak_ram_gb == catalog[GEMMA].ram_gb


# ---- installed / partial ---------------------------------------------------------------------

def test_config_json_alone_is_not_installed(store):
    d = store.model_dir(IT2)
    d.mkdir(parents=True)
    (d / "config.json").write_text("{}")
    assert not store.is_installed(IT2)
    assert "model.SRC" in store.missing_files(IT2)


def test_all_required_files_make_it_installed(store):
    write_it2(store.model_dir(IT2))
    assert store.is_installed(IT2)
    (store.model_dir(IT2) / "model.TGT").unlink()
    assert not store.is_installed(IT2)


def test_download_in_progress_is_not_installed(store):
    downloaded(store, IT2)
    (store.model_dir(IT2) / DOWNLOAD_MARKER).write_text("")
    assert not store.is_installed(IT2) and not store.is_verified(IT2)
    assert store.status(IT2)["downloading"]


def test_mmproj_is_optional_for_text_translation(store):
    d = store.model_dir(GEMMA)
    write_gemma(d)
    (d / "mmproj-gemma-4-E2B-it-f16.gguf").unlink()
    assert store.is_installed(GEMMA)


def test_download_marks_partial_until_complete(store, monkeypatch):
    import huggingface_hub

    def failing(**kw):
        (Path(kw["local_dir"]) / "config.json").write_text("{}")
        raise ConnectionError("network went away")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", failing)
    with pytest.raises(ConnectionError):
        store.download(IT2, log=lambda m: None)
    assert not store.is_installed(IT2) and store.status(IT2)["downloading"]

    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda **kw: write_it2(Path(kw["local_dir"])))
    store.download(IT2, log=lambda m: None)
    assert store.is_installed(IT2) and store.is_verified(IT2)
    assert not (store.model_dir(IT2) / DOWNLOAD_MARKER).exists()


def test_gguf_download_without_the_optional_projector(store, monkeypatch):
    import huggingface_hub

    def fake_file(repo_id, filename, revision, local_dir):
        if filename.startswith("mmproj"):
            raise FileNotFoundError("404")
        (Path(local_dir) / filename).write_bytes(b"GGUF\x03\x00\x00\x00" + b"\0" * 64)

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake_file)
    logs: list[str] = []
    store.download(GEMMA, log=logs.append)
    assert store.is_verified(GEMMA)
    assert any("Optional file mmproj" in m for m in logs)


def test_download_missing_tokenizer_files_fails(store, monkeypatch):
    import huggingface_hub

    def without_spm(**kw):
        write_it2(Path(kw["local_dir"]))
        (Path(kw["local_dir"]) / "model.SRC").unlink()

    monkeypatch.setattr(huggingface_hub, "snapshot_download", without_spm)
    with pytest.raises(RuntimeError, match="model.SRC"):
        store.download(IT2, log=lambda m: None)
    assert not store.is_installed(IT2)


# ---- verify ----------------------------------------------------------------------------------

def test_verify_reports_a_deleted_file(store):
    d = downloaded(store, IT2)
    (d / "generation_config.json").unlink()  # not required, but it was recorded
    logs: list[str] = []
    assert not store.verify(IT2, log=logs.append)
    assert "missing generation_config.json" in logs
    assert not store.is_verified(IT2)


def test_verify_detects_changes_and_keeps_the_reference(store):
    d = downloaded(store, IT2)
    original = (d / "modeling_indictrans.py").read_text()
    (d / "modeling_indictrans.py").write_text("import os  # tampered\n")
    assert not store.verify(IT2, log=lambda m: None)
    assert not store.verify(IT2, log=lambda m: None), "a failed check must not become the new reference"
    (d / "modeling_indictrans.py").write_text(original)
    assert store.verify(IT2, log=lambda m: None)


def test_unknown_folder_with_code_is_not_verified(store):
    write_it2(store.model_dir(IT2))  # copied in by hand: no manifest, no pinned checksums
    logs: list[str] = []
    assert not store.verify(IT2, log=logs.append)
    assert any("modeling_indictrans.py has no known checksum" in m for m in logs)
    assert not store.is_verified(IT2)


def test_unknown_folder_without_code_is_verified_by_structure(store):
    write_gemma(store.model_dir(GEMMA))
    assert store.verify(GEMMA, log=lambda m: None)


def test_pinned_checksums_are_enforced(tmp_path):
    catalog = load_catalog()
    d = tmp_path / "store" / IT2
    write_it2(d)
    catalog[IT2].checksums = {n: sha256_file(d / n) for n in ("modeling_indictrans.py",
                                                              "configuration_indictrans.py",
                                                              "tokenization_indictrans.py")}
    store = ModelStore(tmp_path / "store", catalog)
    assert store.verify(IT2, log=lambda m: None)
    (d / "modeling_indictrans.py").write_text("evil = True\n")
    assert not store.verify(IT2, log=lambda m: None)


def test_store_under_a_dot_cache_folder_still_hashes(tmp_path):
    store = ModelStore(tmp_path / ".cache" / "store")
    downloaded(store, IT2)
    assert store.verify(IT2, log=lambda m: None)


def test_truncated_weights_are_detected(tmp_path):
    good = tmp_path / "model.safetensors"
    good.write_bytes(safetensors_bytes(64))
    assert structure_problem(good) is None
    good.write_bytes(safetensors_bytes(64)[:-10])
    assert "truncated" in structure_problem(good)
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"\0\0")
    assert structure_problem(gguf) == "not a GGUF file"


# ---- pack import -------------------------------------------------------------------------------

def test_importing_the_store_itself_is_refused(store):
    d = downloaded(store, GEMMA)
    with pytest.raises(PackImportError):
        store.import_pack(store.models_dir, log=lambda m: None)
    with pytest.raises(PackImportError):
        store.import_pack(d, log=lambda m: None)
    assert store.is_verified(GEMMA)


def test_damaged_pack_keeps_the_installed_model(store, tmp_path):
    d = downloaded(store, GEMMA)
    before = sha256_file(d / "gemma-4-E2B-it-Q4_K_M.gguf")
    pack = tmp_path / "pack"
    write_gemma(pack / GEMMA, model=b"GG")  # truncated copy
    report = store.import_pack_report(pack, log=lambda m: None)
    assert report["imported"] == [] and GEMMA in report["failed"]
    assert sha256_file(d / "gemma-4-E2B-it-Q4_K_M.gguf") == before
    assert store.is_verified(GEMMA)
    assert [p.name for p in store.models_dir.iterdir()] == [GEMMA]  # no staging left behind


def test_pack_with_unpinned_code_is_refused(store, tmp_path):
    pack = tmp_path / "pack"
    write_it2(pack / IT2)
    (pack / IT2 / "modeling_evil.py").write_text("import os\n")
    report = store.import_pack_report(pack, log=lambda m: None)
    assert report["imported"] == []
    assert any("no known checksum" in p for p in report["failed"][IT2])
    assert not store.is_installed(IT2)


def test_pack_own_manifest_is_not_trusted(store, tmp_path):
    """Copying the pack's manifest must not make its code 'verified'."""
    pack = tmp_path / "pack"
    write_it2(pack / IT2)
    folder = pack / IT2
    listed = {p.name: sha256_file(p) for p in folder.iterdir()}
    (folder / MANIFEST).write_text(json.dumps({"verified": True, "sha256": listed}))
    assert store.import_pack(pack, log=lambda m: None) == []


def test_pack_differing_from_the_downloaded_copy_is_refused(store, tmp_path):
    d = downloaded(store, IT2)
    pack = tmp_path / "pack"
    write_it2(pack / IT2)
    (pack / IT2 / "model.safetensors").write_bytes(safetensors_bytes(32))  # other weights
    report = store.import_pack_report(pack, log=lambda m: None)
    assert "checksum mismatch model.safetensors" in report["failed"][IT2]
    assert (d / "model.safetensors").read_bytes() == safetensors_bytes()


def test_pack_matching_the_recorded_copy_is_imported(store, tmp_path):
    downloaded(store, IT2)
    pack = tmp_path / "pack"
    write_it2(pack / IT2)
    assert store.import_pack(pack, log=lambda m: None) == [IT2]
    assert store.is_verified(IT2)


def test_pinned_pack_is_imported(tmp_path):
    pack = tmp_path / "pack"
    write_it2(pack / IT2)
    catalog = load_catalog()
    catalog[IT2].checksums = {p.name: sha256_file(p) for p in (pack / IT2).iterdir()}
    store = ModelStore(tmp_path / "store", catalog)
    assert store.import_pack(pack, log=lambda m: None) == [IT2]
    assert store.is_verified(IT2) and store.status(IT2)["verified"]


def test_good_gguf_pack_replaces_the_old_copy(store, tmp_path):
    downloaded(store, GEMMA)
    pack = tmp_path / "pack"
    write_gemma(pack / GEMMA, model=b"GGUF\x03\x00\x00\x00" + b"\7" * 64)
    # Same revision, different bytes: refused (the recorded copy is the reference)...
    assert store.import_pack(pack, log=lambda m: None) == []
    # ...but accepted once the old copy is removed (e.g. a newer pack).
    store.remove(GEMMA)
    assert store.import_pack(pack, log=lambda m: None) == [GEMMA]
    assert store.is_verified(GEMMA)


def test_failed_swap_restores_the_old_copy(store, tmp_path, monkeypatch):
    d = downloaded(store, GEMMA)
    pack = tmp_path / "pack"
    write_gemma(pack / GEMMA)
    real_replace = os.replace

    def flaky_replace(src, dst):
        if Path(src).name.startswith(".import-"):
            raise PermissionError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    report = store.import_pack_report(pack, log=lambda m: None)
    monkeypatch.setattr(os, "replace", real_replace)
    assert report["imported"] == [] and GEMMA in report["failed"]
    assert d.is_dir() and store.is_verified(GEMMA)


def test_interrupted_swap_is_recovered(store):
    d = downloaded(store, GEMMA)
    os.replace(d, store.models_dir / f".old-{GEMMA}")  # crash after moving the old copy aside
    store._recover(GEMMA)
    assert store.is_verified(GEMMA)
