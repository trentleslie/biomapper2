import contextlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import cast

import inflect
import requests
import yaml
from bmt import Toolkit
from linkml_runtime.utils.schemaview import SchemaView

from .config import BIOLINK_VERSION_DEFAULT, PROJECT_ROOT, get_cache_dir
from .utils import setup_logging, to_set

setup_logging()


def _get_with_retry(url: str, attempts: int = 3, backoff: float = 1.5, timeout: int = 60) -> requests.Response:
    """GET with a few retries on transient network errors.

    The offline gate's model/prefix downloads happen once per session; a single transient reset
    (seen as 'Connection reset by peer' from GitHub raw under load) should retry rather than fail
    the run. Raises the last error if every attempt fails.
    """
    last_exc: requests.RequestException | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(backoff * attempt)
    assert last_exc is not None
    raise last_exc


def _atomic_write_text(path: str, text: str) -> None:
    """Publish file contents atomically: write a temp file in the same dir, then rename.

    A direct write can leave a truncated file if two workers race at startup or a write is
    interrupted; because the cache trusts any path that exists, a partial file would poison every
    later build. os.replace() is atomic on one filesystem, so readers see either no file or the
    complete one -- never a partial.
    """
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def _atomic_copy_file(src: Path, dst: Path) -> None:
    """Copy src to dst atomically via a same-directory temp file and os.replace."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dst.parent), suffix=".tmp")
    try:
        data = src.read_bytes()
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, str(dst))
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


@lru_cache(maxsize=8)
def _build_toolkit(schema_source: str) -> Toolkit:
    """Build a bmt Toolkit once per schema source (it is read-only, so safe to share).

    Checks local caches for biolink-predicate-mapping.yaml before falling back to network download.
    When a local mapping exists, constructs Toolkit via SchemaView and safe_load to make zero network calls.
    """
    candidates = [
        get_cache_dir() / "biolink-predicate-mapping.yaml",
        PROJECT_ROOT / "cache" / "biolink-predicate-mapping.yaml",
        PROJECT_ROOT / "studies" / "kestrel_fault_benchmark" / "fixtures" / "biolink-predicate-mapping.yaml",
    ]
    for cand in candidates:
        if cand.exists():
            target = get_cache_dir() / "biolink-predicate-mapping.yaml"
            if cand != target and not target.exists():
                with contextlib.suppress(OSError):
                    _atomic_copy_file(cand, target)
            tk = Toolkit.__new__(Toolkit)
            tk.view = SchemaView(schema_source)
            tk.pmap = yaml.safe_load(cand.read_text(encoding="utf-8"))
            return tk

    last_exc: requests.RequestException | None = None
    for attempt in range(1, 4):
        try:
            return Toolkit(schema=schema_source)
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(1.5 * attempt)
    assert last_exc is not None
    raise last_exc


class BiolinkClient:
    """Client for Biolink Model Toolkit operations (with caching)."""

    def __init__(self, biolink_version: str | None = None):
        self.biolink_version = biolink_version if biolink_version else BIOLINK_VERSION_DEFAULT
        biolink_url = (
            f"https://raw.githubusercontent.com/biolink/biolink-model/"
            f"refs/tags/v{self.biolink_version}/biolink-model.yaml"
        )
        logging.info("Initializing bmt (Biolink Model Toolkit)...")
        # Load the model schema from an on-disk cache instead of re-downloading it on every
        # construction. bmt.Toolkit(schema=<url>) fetches the ~400 KB model YAML each time a
        # client is built; the test tree builds a fresh Normalizer()/Mapper() per case, which
        # hammered GitHub raw and made the offline gate flake on transient connection resets.
        # Cache-once-then-load-from-disk mirrors get_prefix_map()'s _load_biolink_file.
        self.bmt = _build_toolkit(self._cached_schema_source(biolink_url))
        self.biolink_ancestors_cache = dict()
        self.biolink_descendants_cache = dict()
        logging.info(f"Initialized BiolinkClient with version {biolink_version}")

    def get_ancestors(self, items: str | Iterable[str] | None) -> set[str]:
        item_set = to_set(items)
        all_ancestors = set()
        for item in item_set:
            if item not in self.biolink_ancestors_cache:
                ancestors = set(self.bmt.get_ancestors(item, formatted=True, mixin=True, reflexive=True))
                self.biolink_ancestors_cache[item] = ancestors
            all_ancestors |= self.biolink_ancestors_cache[item]

        return all_ancestors

    def get_descendants(self, items: str | Iterable[str] | None) -> set[str]:
        item_set = to_set(items)
        all_descendants = set()
        for item in item_set:
            if item not in self.biolink_descendants_cache:
                descendants = set(self.bmt.get_descendants(item, formatted=True, mixin=True, reflexive=True))
                self.biolink_descendants_cache[item] = descendants
            all_descendants |= self.biolink_descendants_cache[item]

        return all_descendants

    def get_prefix_map(self) -> dict[str, str]:
        logging.debug(f"Grabbing biolink prefix map for version: {self.biolink_version}")
        url = (
            f"https://raw.githubusercontent.com/biolink/biolink-model/refs/tags/v{self.biolink_version}/"
            f"project/prefixmap/biolink-model-prefix-map.json"
        )
        prefix_to_iri_map = self._load_biolink_file(url)
        return prefix_to_iri_map

    def _cached_schema_source(self, url: str) -> str:
        """Local path to the cached Biolink model schema, downloading once if absent.

        Returns a filesystem path so bmt.Toolkit loads the schema offline after the first fetch.
        Checks get_cache_dir() first, then PROJECT_ROOT / "cache" (copying to get_cache_dir()).
        If the download fails and nothing is cached yet, fall back to the URL.
        """
        file_name = url.split("/")[-1]  # e.g. biolink-model.yaml
        stem, _, ext = file_name.rpartition(".")
        target_name = f"{stem}_{self.biolink_version}.{ext}"
        cache_dir = get_cache_dir()
        local_path = cache_dir / target_name
        if local_path.exists():
            return str(local_path)

        fallback_paths = [
            PROJECT_ROOT / "cache" / target_name,
            PROJECT_ROOT / "studies" / "kestrel_fault_benchmark" / "fixtures" / target_name,
        ]
        for fallback in fallback_paths:
            if fallback.exists():
                if local_path != fallback:
                    with contextlib.suppress(OSError):
                        _atomic_copy_file(fallback, local_path)
                        return str(local_path)
                return str(fallback)

        try:
            response = _get_with_retry(url)
            cache_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(str(local_path), response.text)
        except requests.RequestException as exc:
            logging.warning(f"Could not cache Biolink schema from {url} ({exc}); loading from URL this run.")
            return url
        return str(local_path)

    def _load_biolink_file(self, url: str) -> dict:
        """Download and cache Biolink model file (or load from cache if already exists).

        Checks get_cache_dir() first, then PROJECT_ROOT / "cache" before attempting HTTP download.

        Args:
            url: URL to Biolink JSON/YAML file

        Returns:
            Parsed JSON content
        """
        file_name = url.split("/")[-1]
        file_name_json = file_name.split(".")[0] + f"_{self.biolink_version}" + ".json"
        cache_dir = get_cache_dir()
        local_path = cache_dir / file_name_json
        logging.debug(f"Local file path is: {local_path}")

        if local_path.exists():
            with open(local_path) as cache_file:
                return json.load(cache_file)

        fallback_paths = [
            PROJECT_ROOT / "cache" / file_name_json,
            PROJECT_ROOT / "studies" / "kestrel_fault_benchmark" / "fixtures" / file_name_json,
        ]
        for fallback in fallback_paths:
            if fallback.exists():
                if local_path != fallback:
                    with contextlib.suppress(OSError):
                        _atomic_copy_file(fallback, local_path)
                with open(fallback) as cache_file:
                    return json.load(cache_file)

        # Download the file if we don't already have it cached
        logging.info(f"Downloading YAML file from {url}. local path is: {local_path}")
        response = _get_with_retry(url)
        if file_name.endswith(".yaml"):
            response_json = yaml.safe_load(response.text)
        else:
            response_json = response.json()

        # Cache the response atomically so a partial write cannot poison the cache.
        cache_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(str(local_path), json.dumps(response_json, indent=2))

        # Read and return the cached JSON
        with open(local_path) as cache_file:
            contents = json.load(cache_file)
            return contents

    def standardize_entity_type(self, entity_type: str) -> str:
        # Map any aliases to their corresponding biolink category
        entity_type_singular = self.singularize(entity_type.removeprefix("biolink:"))
        entity_type_cleaned = "".join(entity_type_singular.lower().split())
        aliases = {
            "metabolite": "SmallMolecule",
            "lipid": "SmallMolecule",
            "clinicallab": "ClinicalFinding",
            "lab": "ClinicalFinding",
        }
        category_raw = aliases.get(entity_type_cleaned, entity_type_cleaned)

        if self.bmt.is_category(category_raw):
            category_element = self.bmt.get_element(category_raw)
            if category_element:
                category = category_element["class_uri"]
                logging.info(f"Biolink category for entity type '{entity_type}' is: {category}")
                return category

        message = (
            f"Could not find valid Biolink category for entity type '{entity_type}'. "
            f"Valid entity types are: {self.get_descendants('NamedThing')}. "
            f"Or accepted aliases are: {aliases}. Will proceed with top-level Biolink category "
            f"of NamedThing (Annotators may be over-selected/not used ideally)."
        )
        logging.warning(message)
        return "biolink:NamedThing"

    @staticmethod
    def singularize(phrase: str) -> str:
        """Singularize the last word of a phrase.

        Examples:
            "metabolites" -> "metabolite"
            "amino acids" -> "amino acid"
            "classes" -> "class"
        """
        _inflect_engine = inflect.engine()

        words = phrase.split()
        if not words:
            return phrase

        last_word = words[-1]
        singular = _inflect_engine.singular_noun(cast(inflect.Word, last_word))

        # singular_noun returns False if the word is already singular
        if singular:
            words[-1] = singular

        return " ".join(words)
