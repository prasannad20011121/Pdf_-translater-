"""Tested model catalog, Hugging Face downloads, model-pack import and checksums (PLAN.md §4.5).

Command line:
    python -m app.model_store list
    python -m app.model_store download gemma4-e2b
    python -m app.model_store import D:\\model-pack
    python -m app.model_store verify gemma4-e2b
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from .config import CATALOG_PATH, get_settings

MANIFEST = ".pdft-manifest.json"


@dataclass
class CatalogEntry:
    id: str
    label: str
    kind: str  # llama-gguf | indictrans2-hf | dev
    ram_gb: float
    min_profile: str
    licence: str
    roles: list[str]
    source: dict[str, Any] = field(default_factory=dict)
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    allow_patterns: list[str] = field(default_factory=list)
    extra_args: list[str] = field(default_factory=list)
    src_lang: str = "hin_Deva"
    tgt_lang: str = "eng_Latn"


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, CatalogEntry]:
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    out: dict[str, CatalogEntry] = {}
    for e in entries:
        known = {k: v for k, v in e.items() if k in CatalogEntry.__dataclass_fields__}
        entry = CatalogEntry(**known)
        out[entry.id] = entry
    return out


def sha256_file(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


class ModelStore:
    def __init__(self, models_dir: Path | None = None, catalog: dict[str, CatalogEntry] | None = None):
        self.models_dir = models_dir or get_settings().models_dir
        self.catalog = catalog if catalog is not None else load_catalog()

    def entry(self, model_id: str) -> CatalogEntry:
        if model_id not in self.catalog:
            raise KeyError(f"'{model_id}' is not in the model catalog")
        return self.catalog[model_id]

    def model_dir(self, model_id: str) -> Path:
        return self.models_dir / model_id

    def file_path(self, model_id: str, key: str) -> Path | None:
        entry = self.entry(model_id)
        spec = entry.files.get(key)
        return self.model_dir(model_id) / spec["name"] if spec else None

    def is_installed(self, model_id: str) -> bool:
        entry = self.entry(model_id)
        if entry.kind == "dev":
            return True
        if entry.kind == "llama-gguf":
            model = self.file_path(model_id, "model")
            return bool(model and model.exists())
        if entry.kind == "indictrans2-hf":
            return (self.model_dir(model_id) / "config.json").exists()
        return False

    def size_bytes(self, model_id: str) -> int:
        d = self.model_dir(model_id)
        return sum(p.stat().st_size for p in d.rglob("*") if p.is_file()) if d.exists() else 0

    def status(self, model_id: str) -> dict[str, Any]:
        entry = self.entry(model_id)
        manifest = self._read_manifest(model_id)
        return {
            "id": entry.id,
            "label": entry.label,
            "kind": entry.kind,
            "ram_gb": entry.ram_gb,
            "licence": entry.licence,
            "roles": entry.roles,
            "min_profile": entry.min_profile,
            "installed": self.is_installed(model_id),
            "size_bytes": self.size_bytes(model_id),
            "verified": bool(manifest.get("verified")),
            "source": entry.source.get("hf_repo"),
            "revision": manifest.get("revision") or entry.source.get("revision"),
        }

    # ---- download / import / verify -------------------------------------------------

    def download(self, model_id: str, log: Callable[[str], None] = print) -> None:
        entry = self.entry(model_id)
        if entry.kind == "dev":
            return
        from huggingface_hub import hf_hub_download, snapshot_download

        repo = entry.source["hf_repo"]
        revision = entry.source.get("revision", "main")
        target = self.model_dir(model_id)
        target.mkdir(parents=True, exist_ok=True)
        if entry.kind == "llama-gguf":
            for key, spec in entry.files.items():
                log(f"Downloading {spec['name']} from {repo} ({key})")
                hf_hub_download(repo_id=repo, filename=spec["name"], revision=revision, local_dir=target)
        else:
            log(f"Downloading {repo}")
            snapshot_download(
                repo_id=repo, revision=revision, local_dir=target,
                allow_patterns=entry.allow_patterns or None,
            )
        self.verify(model_id, record=True, log=log)

    def import_pack(self, pack_dir: Path, log: Callable[[str], None] = print) -> list[str]:
        imported = []
        for model_id in self.catalog:
            src = Path(pack_dir) / model_id
            if not src.is_dir():
                continue
            log(f"Importing {model_id}")
            dst = self.model_dir(model_id)
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            if self.verify(model_id, log=log):
                imported.append(model_id)
        return imported

    def verify(self, model_id: str, record: bool = False, log: Callable[[str], None] = print) -> bool:
        """Check files against the catalog checksums and the manifest.

        record=True (right after a download) stores the checksums as the reference;
        later checks, including after a model-pack import, compare against them.
        """
        entry = self.entry(model_id)
        if entry.kind == "dev":
            return True
        target = self.model_dir(model_id)
        recorded: dict[str, str] = self._read_manifest(model_id).get("sha256", {})
        expected = {spec["name"]: spec.get("sha256") for spec in entry.files.values()}
        files = [p for p in target.rglob("*") if p.is_file() and p.name != MANIFEST and ".cache" not in p.parts]
        actual = {p.relative_to(target).as_posix(): sha256_file(p) for p in files}

        problems = [f"missing {n}" for n in expected if n not in actual]
        for name, digest in actual.items():
            want = expected.get(name) or (None if record else recorded.get(name))
            if want and want != digest:
                problems.append(f"checksum mismatch {name}")
        ok = bool(actual) and not problems
        for p in problems:
            log(p)
        self._write_manifest(model_id, {
            "verified": ok,
            "revision": entry.source.get("revision"),
            "sha256": actual if (record or not recorded) else recorded,
        })
        return ok

    def _read_manifest(self, model_id: str) -> dict[str, Any]:
        path = self.model_dir(model_id) / MANIFEST
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_manifest(self, model_id: str, data: dict[str, Any]) -> None:
        path = self.model_dir(model_id) / MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    store = ModelStore()
    if not argv or argv[0] == "list":
        for model_id in store.catalog:
            s = store.status(model_id)
            mark = "installed" if s["installed"] else "-"
            print(f"{model_id:28} {mark:10} {s['ram_gb']:>4} GB  {s['label']}")
        return 0
    cmd, *rest = argv
    if cmd == "download" and rest:
        store.download(rest[0])
    elif cmd == "import" and rest:
        print("Imported:", ", ".join(store.import_pack(Path(rest[0]))) or "nothing")
    elif cmd == "verify" and rest:
        print("OK" if store.verify(rest[0]) else "FAILED")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
