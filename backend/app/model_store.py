"""Tested model catalog, Hugging Face downloads, model-pack import and checksums (PLAN.md §4.5).

Command line:
    python -m app.model_store list
    python -m app.model_store download gemma4-e2b
    python -m app.model_store import D:\\model-pack
    python -m app.model_store verify gemma4-e2b

Trust rules:
- A model counts as installed only when every required file is present and no
  download is still in progress (a partial download is never "installed").
- Checksums come from the catalog (pinned in Phase 0) or, until then, are recorded
  right after a download from the pinned Hugging Face repo. Later checks compare
  against them and report missing, changed or damaged files.
- A model pack is copied to a staging folder, checked there, and only then swapped
  in; if anything fails the installed copy is untouched. The pack's own checksum
  list is only used to detect a damaged copy, never as proof of authenticity.
- Executable files (the *.py code IndicTrans2 loads with trust_remote_code, or
  pickle weights) are never accepted from a pack or an unknown folder unless their
  sha256 is pinned in the catalog or was recorded from a download.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from .config import CATALOG_PATH, get_settings

MANIFEST = ".pdft-manifest.json"
DOWNLOAD_MARKER = ".pdft-downloading"
STAGING_PREFIX = ".import-"
BACKUP_PREFIX = ".old-"
# Files that run code when a model is loaded: Python (trust_remote_code) and pickles.
EXECUTABLE_SUFFIXES = (".py", ".pyc", ".pyw", ".pyd", ".so", ".dll", ".exe",
                       ".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt")


class PackImportError(ValueError):
    """The pack folder can't be imported at all (for example, it is the model store)."""


@dataclass
class CatalogEntry:
    id: str
    label: str
    kind: str  # llama-gguf | indictrans2-hf | dev
    ram_gb: float  # memory while running
    min_profile: str
    licence: str
    roles: list[str]
    source: dict[str, Any] = field(default_factory=dict)
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    allow_patterns: list[str] = field(default_factory=list)
    extra_args: list[str] = field(default_factory=list)
    src_lang: str = "hin_Deva"
    tgt_lang: str = "eng_Latn"
    # Peak memory while loading, when higher than ram_gb (IndicTrans2 loads fp32
    # weights before quantising them to int8).
    load_ram_gb: float | None = None
    # Files that must all be present; an item that is a list means "one of these".
    required_files: list[Any] = field(default_factory=list)
    # Pinned sha256 per file path (relative to the model folder), filled in Phase 0.
    checksums: dict[str, str | None] = field(default_factory=dict)

    @property
    def peak_ram_gb(self) -> float:
        """What the memory guard must find free: the larger of load peak and running size."""
        return max(float(self.ram_gb), float(self.load_ram_gb or 0.0))

    def required_groups(self) -> list[list[str]]:
        groups: list[list[str]] = []
        for item in self.required_files:
            group = [str(x) for x in item] if isinstance(item, (list, tuple)) else [str(item)]
            if group not in groups:
                groups.append(group)
        for spec in self.files.values():
            if not spec.get("optional") and [spec["name"]] not in groups:
                groups.append([spec["name"]])
        return groups

    def pinned(self) -> dict[str, str]:
        pins = {name: str(sha).lower() for name, sha in self.checksums.items() if sha}
        for spec in self.files.values():
            if spec.get("sha256"):
                pins[spec["name"]] = str(spec["sha256"]).lower()
        return pins


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


def is_executable(name: str) -> bool:
    return name.lower().endswith(EXECUTABLE_SUFFIXES)


def structure_problem(path: Path) -> str | None:
    """Cheap checks that catch truncated or wrong weight files without a checksum."""
    suffix = path.suffix.lower()
    try:
        size = path.stat().st_size
        if suffix == ".gguf":
            with path.open("rb") as f:
                head = f.read(8)
            if len(head) < 8 or head[:4] != b"GGUF":
                return "not a GGUF file"
            version = int.from_bytes(head[4:8], "little")
            if version not in (1, 2, 3):
                return f"unknown GGUF version {version}"
        elif suffix == ".safetensors":
            with path.open("rb") as f:
                n = int.from_bytes(f.read(8), "little")
                if size < 8 or n <= 0 or 8 + n > size or n > 100 * 1024 * 1024:
                    return "damaged or truncated header"
                header = json.loads(f.read(n))
            end = max((int(v["data_offsets"][1]) for k, v in header.items() if k != "__metadata__"), default=0)
            if 8 + n + end > size:
                return f"truncated ({size:,} of {8 + n + end:,} bytes)"
    except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
        return f"unreadable ({type(e).__name__})"
    return None


def _content_files(folder: Path) -> dict[str, Path]:
    """Model files in a folder, by relative path (no manifest, marker or HF cache)."""
    out: dict[str, Path] = {}
    if not folder.is_dir():
        return out
    for p in folder.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(folder)
        if ".cache" in rel.parts or p.name.startswith(".pdft-"):  # manifest, marker, temp files
            continue
        out[rel.as_posix()] = p
    return out


def _overlaps(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a in b.parents or b in a.parents


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    # ---- state -------------------------------------------------------------------------

    def missing_files(self, model_id: str) -> list[str]:
        """Required files that are not on disk ("a or b" for alternatives)."""
        entry = self.entry(model_id)
        if entry.kind == "dev":
            return []
        d = self.model_dir(model_id)
        return [" or ".join(g) for g in entry.required_groups() if not any((d / n).is_file() for n in g)]

    def is_downloading(self, model_id: str) -> bool:
        return (self.model_dir(model_id) / DOWNLOAD_MARKER).exists()

    def is_installed(self, model_id: str) -> bool:
        entry = self.entry(model_id)
        if entry.kind == "dev":
            return True
        if entry.kind not in ("llama-gguf", "indictrans2-hf"):
            return False
        if not self.model_dir(model_id).is_dir() or self.is_downloading(model_id):
            return False
        return not self.missing_files(model_id)

    def is_verified(self, model_id: str) -> bool:
        """Installed, and its last check passed (only verified models are used)."""
        if self.entry(model_id).kind == "dev":
            return True
        return self.is_installed(model_id) and self._read_manifest(model_id).get("verified") is True

    def size_bytes(self, model_id: str) -> int:
        d = self.model_dir(model_id)
        return sum(p.stat().st_size for p in d.rglob("*") if p.is_file()) if d.exists() else 0

    def status(self, model_id: str) -> dict[str, Any]:
        entry = self.entry(model_id)
        manifest = self._read_manifest(model_id)
        installed = self.is_installed(model_id)
        return {
            "id": entry.id,
            "label": entry.label,
            "kind": entry.kind,
            "ram_gb": entry.ram_gb,
            "load_ram_gb": entry.peak_ram_gb,
            "licence": entry.licence,
            "roles": entry.roles,
            "min_profile": entry.min_profile,
            "installed": installed,
            "size_bytes": self.size_bytes(model_id),
            "verified": installed and manifest.get("verified") is True,
            "missing": self.missing_files(model_id) if self.model_dir(model_id).exists() else [],
            "problems": list(manifest.get("problems", [])),
            "downloading": self.is_downloading(model_id),
            "source": entry.source.get("hf_repo"),
            "revision": manifest.get("revision") or entry.source.get("revision"),
        }

    # ---- checks ------------------------------------------------------------------------

    def _check_folder(
        self, entry: CatalogEntry, folder: Path, reference: dict[str, str],
        trusted: bool, require_reference_files: bool,
    ) -> tuple[dict[str, str], list[str]]:
        """Hash a folder's files and list what is wrong with them.

        reference: checksums recorded earlier (from a download). trusted: the files
        just came from the pinned Hugging Face repo, so unpinned code is accepted.
        """
        files = _content_files(folder)
        actual = {name: sha256_file(p) for name, p in files.items()}
        problems: list[str] = []
        for group in entry.required_groups():
            if not any(n in actual for n in group):
                problems.append(f"missing {' or '.join(group)}")
        if require_reference_files:
            problems += [f"missing {n}" for n in reference if n not in actual and f"missing {n}" not in problems]
        pins = entry.pinned()
        for name, digest in sorted(actual.items()):
            want = pins.get(name) or reference.get(name)
            if want and want.lower() != digest:
                problems.append(f"checksum mismatch {name}")
            elif not want and not trusted and is_executable(name):
                problems.append(f"executable file {name} has no known checksum "
                                f"(pin its sha256 in models/catalog.yaml)")
            damage = structure_problem(files[name])
            if damage:
                problems.append(f"{name}: {damage}")
        return actual, problems

    def verify(self, model_id: str, record: bool = False, log: Callable[[str], None] = print) -> bool:
        """Check the installed files against pinned and recorded checksums.

        record=True (right after a download from the pinned repo) stores the checksums
        as the reference; later checks compare against them. Recorded checksums are
        never replaced by those of files that failed a check.
        """
        entry = self.entry(model_id)
        if entry.kind == "dev":
            return True
        target = self.model_dir(model_id)
        if not target.is_dir():
            log(f"{entry.label} is not installed")
            return False
        manifest = self._read_manifest(model_id)
        recorded: dict[str, str] = manifest.get("sha256") or {}
        actual, problems = self._check_folder(
            entry, target, {} if record else recorded, trusted=record, require_reference_files=not record)
        if self.is_downloading(model_id):
            problems.append("download not finished")
        ok = bool(actual) and not problems
        for p in problems:
            log(p)
        if ok and (record or not recorded):
            reference, revision, source = actual, entry.source.get("revision"), ("download" if record else "local")
        else:
            reference = recorded
            revision = manifest.get("revision") or entry.source.get("revision")
            source = manifest.get("source", "")
        self._write_manifest(target, {
            "verified": ok,
            "revision": revision,
            "source": source,
            "checked_at": _now(),
            "problems": problems,
            "sha256": reference,
        })
        return ok

    # ---- download --------------------------------------------------------------------

    def download(self, model_id: str, log: Callable[[str], None] = print) -> None:
        entry = self.entry(model_id)
        if entry.kind == "dev":
            return
        from huggingface_hub import hf_hub_download, snapshot_download

        repo = entry.source["hf_repo"]
        revision = entry.source.get("revision", "main")
        self._recover(model_id)
        target = self.model_dir(model_id)
        target.mkdir(parents=True, exist_ok=True)
        marker = target / DOWNLOAD_MARKER
        marker.write_text(_now(), encoding="utf-8")  # stays if the download stops halfway
        if entry.kind == "llama-gguf":
            for key, spec in entry.files.items():
                log(f"Downloading {spec['name']} from {repo} ({key})")
                try:
                    hf_hub_download(repo_id=repo, filename=spec["name"], revision=revision, local_dir=target)
                except Exception as e:
                    if not spec.get("optional"):
                        raise
                    # e.g. the vision projector: text translation works without it
                    log(f"Optional file {spec['name']} was not downloaded: {e}")
        else:
            log(f"Downloading {repo}")
            snapshot_download(
                repo_id=repo, revision=revision, local_dir=target,
                allow_patterns=entry.allow_patterns or None,
            )
        missing = self.missing_files(model_id)
        if missing:
            raise RuntimeError(f"download incomplete, missing: {', '.join(missing)}")
        marker.unlink(missing_ok=True)
        if not self.verify(model_id, record=True, log=log):
            raise RuntimeError("the downloaded files failed verification")

    # ---- model packs --------------------------------------------------------------------

    def import_pack(self, pack_dir: Path, log: Callable[[str], None] = print) -> list[str]:
        """Import every catalog model found in a pack folder; returns the imported ids."""
        return self.import_pack_report(pack_dir, log=log)["imported"]

    def import_pack_report(self, pack_dir: Path, log: Callable[[str], None] = print) -> dict[str, Any]:
        """Like import_pack, with the reasons models were not imported:
        {"imported": [ids], "failed": {id: [problems]}}."""
        pack = Path(pack_dir).resolve()
        store = Path(self.models_dir).resolve()
        if pack == store or store in pack.parents:
            raise PackImportError("That folder is the model store itself. Choose the model pack folder.")
        report: dict[str, Any] = {"imported": [], "failed": {}}
        for model_id, entry in self.catalog.items():
            src = pack / model_id
            if entry.kind == "dev" or not src.is_dir():
                continue
            dst = self.model_dir(model_id)
            if _overlaps(src, dst):
                report["failed"][model_id] = ["the pack folder overlaps the installed model folder"]
                continue
            log(f"Importing {model_id}")
            try:
                problems = self._import_one(entry, src, dst, log)
            except OSError as e:
                problems = [f"could not replace the installed copy ({e}); "
                            "stop running translations and try again"]
            for p in problems:
                log(f"{model_id}: {p}")
            if problems:
                report["failed"][model_id] = problems
            else:
                report["imported"].append(model_id)
        return report

    def _trusted_reference(self, model_id: str) -> dict[str, str]:
        """Checksums recorded for the installed copy, if they are for the same revision."""
        manifest = self._read_manifest(model_id)
        revision = self.entry(model_id).source.get("revision")
        if manifest.get("revision") not in (None, revision):
            return {}
        return dict(manifest.get("sha256") or {})

    def _import_one(self, entry: CatalogEntry, src: Path, dst: Path, log: Callable[[str], None]) -> list[str]:
        self._recover(entry.id)
        staging = self.models_dir / f"{STAGING_PREFIX}{entry.id}.tmp"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            self.models_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, staging, ignore=shutil.ignore_patterns(MANIFEST, DOWNLOAD_MARKER, ".cache"))
            # Read before anything is replaced: the installed copy's recorded checksums.
            reference = self._trusted_reference(entry.id)
            actual, problems = self._check_folder(
                entry, staging, reference, trusted=False, require_reference_files=False)
            problems += self._pack_manifest_problems(src, actual)
            if problems:
                return problems
            self._write_manifest(staging, {
                "verified": True,
                "revision": entry.source.get("revision"),
                "source": "import",
                "checked_at": _now(),
                "problems": [],
                "sha256": actual,
            })
            self._swap_in(staging, dst)
            return []
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _pack_manifest_problems(src: Path, actual: dict[str, str]) -> list[str]:
        """The pack's own checksum list can reveal a damaged copy (not tampering)."""
        try:
            listed = json.loads((src / MANIFEST).read_text(encoding="utf-8")).get("sha256") or {}
        except (OSError, ValueError, AttributeError):
            return []
        problems = []
        for name, digest in listed.items():
            if name not in actual:
                problems.append(f"missing {name} (listed in the pack)")
            elif str(digest).lower() != actual[name]:
                problems.append(f"{name} does not match the pack's checksum (damaged copy?)")
        return problems

    def _swap_in(self, staging: Path, dst: Path) -> None:
        """Replace dst with staging: old copy aside, new copy in, old copy deleted.
        If the new copy can't be moved in, the old one is put back."""
        backup = self.models_dir / f"{BACKUP_PREFIX}{dst.name}"
        shutil.rmtree(backup, ignore_errors=True)
        had_old = dst.exists()
        if had_old:
            os.replace(dst, backup)  # fails (and changes nothing) if a file is in use on Windows
        try:
            os.replace(staging, dst)
        except OSError:
            if had_old:
                os.replace(backup, dst)
            raise
        shutil.rmtree(backup, ignore_errors=True)

    def _recover(self, model_id: str) -> None:
        """Finish a swap that a crash interrupted, and drop stale staging folders."""
        dst = self.model_dir(model_id)
        backup = self.models_dir / f"{BACKUP_PREFIX}{model_id}"
        if backup.exists():
            if dst.exists():
                shutil.rmtree(backup, ignore_errors=True)
            else:
                os.replace(backup, dst)
        shutil.rmtree(self.models_dir / f"{STAGING_PREFIX}{model_id}.tmp", ignore_errors=True)

    def remove(self, model_id: str) -> None:
        """Delete an installed model (Settings > Models > Remove)."""
        if self.entry(model_id).kind == "dev":
            return
        shutil.rmtree(self.model_dir(model_id), ignore_errors=True)

    # ---- manifest -----------------------------------------------------------------------

    def _read_manifest(self, model_id: str) -> dict[str, Any]:
        path = self.model_dir(model_id) / MANIFEST
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write_manifest(folder: Path, data: dict[str, Any]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / (MANIFEST + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, folder / MANIFEST)


def main(argv: list[str]) -> int:
    store = ModelStore()
    if not argv or argv[0] == "list":
        for model_id in store.catalog:
            s = store.status(model_id)
            mark = ("verified" if s["verified"] else "installed") if s["installed"] else "-"
            print(f"{model_id:28} {mark:10} {s['ram_gb']:>4} GB  {s['label']}")
        return 0
    cmd, *rest = argv
    if cmd == "download" and rest:
        store.download(rest[0])
    elif cmd == "import" and rest:
        report = store.import_pack_report(Path(rest[0]))
        print("Imported:", ", ".join(report["imported"]) or "nothing")
        for model_id, problems in report["failed"].items():
            print(f"Not imported: {model_id}: {'; '.join(problems)}")
    elif cmd == "verify" and rest:
        print("OK" if store.verify(rest[0]) else "FAILED")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
