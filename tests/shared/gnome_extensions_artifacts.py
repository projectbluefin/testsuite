"""Validate packaged GNOME Shell extension ZIPs against a pinned contract.

Used by the four-profile GNOME OS gate (issue #909) to reject an extension
artifact *before* it is extracted or installed, so a Bluefin smoke failure can
never be misattributed to an extension that was never actually installed.

This is the "reviewed builder isolated from the trusted scheduler" validation
from agent-plan step 1: it only inspects the archive, it never extracts to the
host and it carries no EGO credentials or upload path. The actual GNOME OS
guest that consumes the validated artifact comes from #908, so this module is
fully testable without a VM.

Validation stages, in order:

0. If ``zip_sha256`` is set on the contract, the archive SHA256 must match.
   This runs first so a pinned artifact is rejected before any member of it
   is inflated. **No canonical contract pins a hash yet** (see
   :data:`CANONICAL_CONTRACTS`), so this stage is currently inert for every
   artifact :func:`main` validates; it only guards contracts a caller pins
   itself.
1. Before reading metadata, reject duplicate names, non-canonical paths,
   symlinks/special files and file/directory aliases. Extraction must not
   interpret a different member tree from the one inspected here.
2. ``metadata.json`` inside the ZIP must declare the contract ``uuid``. The
   CLI also *resolves* the contract from that declared UUID (see :func:`main`),
   so an archive is never judged against a contract it was merely passed next
   to on the command line.
3. Every path in ``required_paths`` must be present in the ZIP. Those paths
   are the members the packaging recipe actually ships and the shell actually
   loads — compiled resources, ``lib/`` modules, schemas — not just the
   manifest, so a ZIP that would fail to load in the guest is rejected here
   instead of being misattributed to Bluefin later.

Every failure records its own category on the result as it is appended, so
rewording a message can never silently reclassify it. Callers read the
category via :func:`classify`.
"""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# metadata.json is the single source of truth for an extension's UUID. Every
# archive produced by `gnome-extensions pack` — including the packed
# just-perfection build and the binhnguyensoft.com widgets — places it at the
# ZIP root, so "metadata.json" is the path that matters in practice. The
# "src/metadata.json" fallback only matches an unpacked source checkout zipped
# verbatim; such an archive still fails `required_paths`, but reading its UUID
# lets the gate report an artifact failure instead of a metadata one.
_METADATA_PATHS = ("metadata.json", "src/metadata.json")

#: Upper bound on the *uncompressed* size of ``metadata.json``. Real extension
#: manifests are well under a kilobyte; anything larger is a zip bomb, so the
#: member is rejected on its declared size before it is inflated.
_MAX_METADATA_BYTES = 1 << 20  # 1 MiB

#: Failure categories reported by :func:`classify`.
CATEGORY_HARNESS = "harness"
CATEGORY_METADATA = "metadata"
CATEGORY_ARTIFACT = "artifact"

#: Packaging recipes a canonical artifact may be produced by. The recipe is part
#: of the pinned identity (#909 step 1): the same revision packed a different way
#: yields a different member set, so the recipe is asserted and reported.
RECIPE_BUILD_SH = (
    "scripts/build.sh (gnome-extensions pack src "
    "--extra-source=data/resources.gresource --extra-source=lib)"
)
RECIPE_PACK_FROM_ROOT = "gnome-extensions pack (repository root)"
RECIPE_UNSPECIFIED = "unspecified"


class ArtifactValidationError(Exception):
    """Raised when the ZIP cannot be opened or is not a valid extension archive.

    ``category`` carries the failure category the caller should report, so an
    unreadable archive (a harness fault) is never reported as a bad manifest.
    """

    def __init__(self, message: str, category: str = CATEGORY_METADATA) -> None:
        super().__init__(message)
        self.category = category


def _parse_metadata(raw: bytes) -> dict:
    """Parse ``metadata.json`` bytes, raising on malformed/non-object JSON.

    A well-formed archive always carries a JSON object here; anything else
    (invalid JSON, a JSON array/list, bytes that are not valid UTF-8) is an
    unsupported-metadata problem and is reported rather than escaping as an
    uncaught exception. ``ValueError`` is caught rather than
    ``json.JSONDecodeError`` because ``json.loads`` raises ``UnicodeDecodeError``
    — a ``ValueError`` subclass that is *not* a ``JSONDecodeError`` — for
    non-UTF-8 bytes.
    """
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ArtifactValidationError(f"malformed metadata.json: {exc}") from exc
    if not isinstance(data, dict):
        raise ArtifactValidationError(
            f"metadata.json is not a JSON object: {type(data).__name__}"
        )
    return data


def _metadata_in(zf: zipfile.ZipFile, names: set[str]) -> dict:
    """Return the first ``metadata.json`` found in an open archive, else raise.

    The member's declared uncompressed size is checked against
    :data:`_MAX_METADATA_BYTES` before anything is inflated, so a highly
    compressible manifest cannot exhaust memory.
    """
    for meta in _METADATA_PATHS:
        if meta in names:
            info = zf.getinfo(meta)
            if info.file_size > _MAX_METADATA_BYTES:
                raise ArtifactValidationError(
                    f"{meta} is implausibly large: {info.file_size} bytes "
                    f"(limit {_MAX_METADATA_BYTES})"
                )
            return _parse_metadata(zf.read(meta))
    raise ArtifactValidationError("no metadata.json found in archive")


def _duplicate_names(zf: zipfile.ZipFile) -> list[str]:
    """Return member names that appear more than once in the central directory.

    ``zipfile`` resolves a repeated name to the *last* entry, while extractors
    differ; an archive that validates on one member and installs another is
    never acceptable, so duplicates are rejected outright.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in zf.namelist():
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    return sorted(duplicates)


def _check_members(zf: zipfile.ZipFile) -> None:
    """Reject names and file types that can escape or alias a guest install.

    Inspect the original name (ZipInfo truncates names at NUL) and reject
    non-canonical paths rather than relying on an extractor's sanitization.
    Ordinary directory entries are allowed, but links and special files are
    not. No archive member is inflated here.
    """
    duplicates = _duplicate_names(zf)
    if duplicates:
        raise ArtifactValidationError(
            "duplicate member names: " + ", ".join(duplicates), CATEGORY_ARTIFACT
        )
    files: set[str] = set()
    directories: set[str] = set()
    for info in zf.infolist():
        name = info.orig_filename
        path = name[:-1] if info.is_dir() else name
        if (
            not path
            or any(c in name for c in ("\0", "\\", ":"))
            or any(part in ("", ".", "..") for part in path.split("/"))
        ):
            raise ArtifactValidationError(
                f"unsafe archive path: {name!r}", CATEGORY_ARTIFACT
            )
        mode_type = stat.S_IFMT(info.external_attr >> 16) if info.create_system == 3 else 0
        expected_type = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
        if mode_type not in (0, expected_type):
            raise ArtifactValidationError(
                f"unsupported archive member type: {name!r}", CATEGORY_ARTIFACT
            )
        (directories if info.is_dir() else files).add(path)
        parts = path.split("/")
        directories.update("/".join(parts[:i]) for i in range(1, len(parts)))
    conflicts = files & directories
    if conflicts:
        raise ArtifactValidationError(
            "archive file/directory conflicts: " + ", ".join(sorted(conflicts)),
            CATEGORY_ARTIFACT,
        )


@dataclass(frozen=True)
class ExtensionContract:
    """The pinned identity of one packaged extension.

    ``required_paths`` lists every member the extension's packaging recipe
    ships that the shell needs in order to load — including compiled
    resources, ``lib/`` modules and schemas — so a structurally incomplete ZIP
    is rejected before it is installed.

    ``package_recipe`` names the exact packaging command the artifact must come
    from (issue #909 step 1 asks for the package recipe identity alongside the
    revision, UUID and hash). It is reported with every result, so a ZIP built
    by the wrong recipe is visible in the gate output instead of being buried
    in a source comment.

    ``zip_sha256`` is optional: structural validation (UUID + required paths)
    always runs, but the hash check is skipped until the pinned build produces
    an immutable ZIP. See :data:`CANONICAL_CONTRACTS`.
    """

    uuid: str
    source_repo: str
    source_rev: str
    required_paths: tuple[str, ...] = ()
    zip_sha256: str | None = None
    package_recipe: str = RECIPE_UNSPECIFIED

    @property
    def label(self) -> str:
        return f"{self.uuid} ({self.source_repo}@{self.source_rev[:8]})"

    @property
    def identity(self) -> str:
        """One-line full identity: revision, UUID, recipe and pinned hash."""
        sha = self.zip_sha256.strip().lower() if self.zip_sha256 else "unpinned"
        return f"{self.label} recipe={self.package_recipe} sha256={sha}"


@dataclass
class ExtensionValidationResult:
    """Outcome of validating one artifact against one contract."""

    contract: ExtensionContract
    uuid_found: str | None = None
    required_missing: list[str] = field(default_factory=list)
    sha256_expected: str | None = None
    sha256_actual: str | None = None
    errors: list[str] = field(default_factory=list)
    #: Category of the *first* failure recorded, set when the error is
    #: appended so classification never depends on message wording.
    category: str | None = None

    def fail(self, category: str, message: str) -> None:
        """Record one failure and its category (first category wins)."""
        self.errors.append(message)
        if self.category is None:
            self.category = category

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def metadata_ok(self) -> bool:
        return self.uuid_found == self.contract.uuid


def _sha256_zip(zip_path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(zip_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_extension_zip(zip_path: str | Path, contract: ExtensionContract) -> ExtensionValidationResult:
    """Validate ``zip_path`` against ``contract``.

    Never raises for a contract mismatch — structural problems are reported on
    the returned :class:`ExtensionValidationResult` so the caller can decide
    whether they block the gate. Only an unreadable archive raises
    :class:`ArtifactValidationError`.
    """
    zip_path = Path(zip_path)
    result = ExtensionValidationResult(
        contract=contract,
        sha256_expected=contract.zip_sha256,
    )

    # Stage 0: when the build is pinned, the hash decides before any member is
    # inflated — a tampered archive never reaches the parsing code below. No
    # canonical contract pins a hash yet, so this is skipped in the gate today.
    if contract.zip_sha256:
        try:
            result.sha256_actual = _sha256_zip(zip_path)
        except OSError as exc:
            result.fail(CATEGORY_HARNESS, f"archive unreadable: {exc}")
            return result
        # Hex digests are case-insensitive; a contract pinned in uppercase must
        # not read as a mismatch.
        if result.sha256_actual.lower() != contract.zip_sha256.strip().lower():
            result.fail(
                CATEGORY_ARTIFACT,
                f"SHA256 mismatch: expected {contract.zip_sha256}, "
                f"got {result.sha256_actual}",
            )
            return result

    try:
        with zipfile.ZipFile(zip_path) as zf:  # single handle for read + namelist
            names = set(zf.namelist())
            try:
                _check_members(zf)
            except ArtifactValidationError as exc:
                result.fail(exc.category, str(exc))
                return result
            try:
                metadata = _metadata_in(zf, names)
            except ArtifactValidationError as exc:
                # Stage-1 metadata problem: the archive is readable but its
                # metadata.json is missing or malformed, so it declares no usable
                # UUID. Report it as a metadata failure, not a harness one.
                result.fail(
                    CATEGORY_METADATA,
                    f"UUID mismatch: archive metadata could not be read ({exc}), "
                    f"contract expects {contract.uuid!r}",
                )
                return result
    except zipfile.BadZipFile as exc:
        result.fail(CATEGORY_HARNESS, f"archive unreadable: {exc}")
        return result
    except OSError as exc:
        result.fail(CATEGORY_HARNESS, f"archive unreadable: {exc}")
        return result

    result.uuid_found = metadata.get("uuid")
    if result.uuid_found != contract.uuid:
        result.fail(
            CATEGORY_METADATA,
            f"UUID mismatch: archive declares {metadata.get('uuid')!r}, "
            f"contract expects {contract.uuid!r}",
        )

    result.required_missing = [p for p in contract.required_paths if p not in names]
    if result.required_missing:
        result.fail(
            CATEGORY_ARTIFACT,
            "missing required paths: " + ", ".join(sorted(result.required_missing)),
        )

    return result


def classify(result: ExtensionValidationResult) -> str:
    """Classify a failure for the gate report.

    The category is read straight off the result, where
    :meth:`ExtensionValidationResult.fail` recorded it alongside the first
    error, so message wording and classification cannot drift apart.

    Returns one of:

    * ``"ok"`` — the artifact passed every check.
    * ``"harness"`` — the archive could not be read (infra/provisioning fault).
    * ``"metadata"`` — the wrong extension was staged (unsupported metadata).
    * ``"artifact"`` — the right extension but wrong/corrupt ZIP (hash or paths).
    """
    if result.valid:
        return "ok"
    return result.category or CATEGORY_ARTIFACT


#: Canonical contract for the four extensions in issue #909.
#:
#: ``source_rev`` is the pinned HEAD of each hive repo (verified immutable at
#: commit time). ``required_paths`` mirrors what that revision's packaging
#: recipe actually emits, checked against the upstream tree at the pinned rev:
#: a ZIP missing any of them installs an extension that cannot load.
#:
#: ``zip_sha256`` is ``None`` for every contract below, so the stage-0 hash gate
#: does not run for anything :func:`main` validates today; structural
#: validation is what currently catches a mis-attributed smoke failure.
#: TODO(#908): pin ``zip_sha256`` here once #908's builder publishes the
#: immutable packaged ZIP per revision — only then is stage 0 a real tamper
#: guarantee.
CANONICAL_CONTRACTS: tuple[ExtensionContract, ...] = (
    # Packed by scripts/build.sh: `gnome-extensions pack src` plus
    # --extra-source=data/resources.gresource and --extra-source=lib, so the
    # compiled resource bundle and the lib/ modules are part of the artifact.
    ExtensionContract(
        uuid="just-perfection-desktop@just-perfection",
        source_repo="gnome-extensions-hive/just-perfection",
        source_rev="6e82a6ebf8e9578f2ffe4e06b88f5d23f600b947",
        package_recipe=RECIPE_BUILD_SH,
        required_paths=(
            "metadata.json",
            "extension.js",
            "prefs.js",
            "stylesheet.css",
            "data/resources.gresource",
            "lib/API.js",
            "lib/Manager.js",
            "lib/Prefs/Prefs.js",
            "lib/Prefs/PrefsKeys.js",
            "schemas/org.gnome.shell.extensions.just-perfection.gschema.xml",
        ),
    ),
    # Packaged from the repo root; schemas/gschemas.compiled is committed at
    # this rev and is what the shell loads for the extension's settings.
    ExtensionContract(
        uuid="sjc-gold@binhnguyensoft.com",
        source_repo="gnome-extensions-hive/sjc-gold-binhnguyensoft.com",
        source_rev="1588c7683d113e42d2f36a69165a9bacd6b1d95b",
        package_recipe=RECIPE_PACK_FROM_ROOT,
        required_paths=(
            "metadata.json",
            "extension.js",
            "prefs.js",
            "sjc_price.py",
            "schemas/org.gnome.shell.extensions.sjc-gold-binhnguyensoft-com.gschema.xml",
            "schemas/gschemas.compiled",
        ),
    ),
    # Packaged from the repo root; no compiled schema is committed at this rev,
    # so only the source gschema.xml is required.
    ExtensionContract(
        uuid="shade-inactive-windows-reborn@binhnguyensoft.com",
        source_repo="gnome-extensions-hive/Shade-Inactive-Windows-Reborn",
        source_rev="59b0afaf7320f72ef408621dafac19ec0214705b",
        package_recipe=RECIPE_PACK_FROM_ROOT,
        required_paths=(
            "metadata.json",
            "extension.js",
            "prefs.js",
            "schemas/org.gnome.shell.extensions.shade-inactive-windows-reborn.gschema.xml",
        ),
    ),
    # Packaged from the repo root; schemas/gschemas.compiled is committed.
    ExtensionContract(
        uuid="stock-market@binhnguyensoft.com",
        source_repo="gnome-extensions-hive/stock-market-binhnguyensoft.com",
        source_rev="667e40171ca6249b846e72cf28e314c5f3a79832",
        package_recipe=RECIPE_PACK_FROM_ROOT,
        required_paths=(
            "metadata.json",
            "extension.js",
            "prefs.js",
            "language.js",
            "stocks_fetch.py",
            "schemas/org.gnome.shell.extensions.stock-market-binhnguyensoft-com.gschema.xml",
            "schemas/gschemas.compiled",
        ),
    ),
)


def find_contract(uuid: str) -> ExtensionContract | None:
    """Return the canonical contract matching ``uuid``, if any."""
    for contract in CANONICAL_CONTRACTS:
        if contract.uuid == uuid:
            return contract
    return None


def validate_all(zip_by_uuid: dict[str, str | Path]) -> list[ExtensionValidationResult]:
    """Validate one staged ZIP per contract key in ``zip_by_uuid``.

    Keys are contract ``uuid`` values; unknown keys are reported as an error and
    classified as ``"artifact"`` rather than silently ignored, so a mis-staged
    file is never missed.
    """
    by_uuid = {c.uuid: c for c in CANONICAL_CONTRACTS}
    results: list[ExtensionValidationResult] = []
    for uuid, zip_path in zip_by_uuid.items():
        contract = by_uuid.get(uuid)
        if contract is None:
            result = ExtensionValidationResult(contract=ExtensionContract(
                uuid=uuid, source_repo="?", source_rev="?"
            ))
            result.fail(CATEGORY_ARTIFACT, "no canonical contract for this UUID")
            results.append(result)
            continue
        results.append(validate_extension_zip(zip_path, contract))
    return results


def read_archive_uuid(zip_path: str | Path) -> str:
    """Return the UUID declared by an archive's ``metadata.json``.

    This is how the gate decides *which* contract an artifact must be judged
    against: the archive names itself, so the caller never has to know the
    order of :data:`CANONICAL_CONTRACTS` or the order a shell glob expanded in.

    Raises :class:`ArtifactValidationError` — with ``category`` set to
    ``harness`` for an unreadable archive, ``artifact`` for an unsafe member
    tree, and ``metadata`` for a readable one that declares no usable UUID.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _check_members(zf)
            metadata = _metadata_in(zf, set(zf.namelist()))
    except zipfile.BadZipFile as exc:
        raise ArtifactValidationError(
            f"archive unreadable: {exc}", CATEGORY_HARNESS
        ) from exc
    except OSError as exc:
        raise ArtifactValidationError(
            f"archive unreadable: {exc}", CATEGORY_HARNESS
        ) from exc
    uuid = metadata.get("uuid")
    if not isinstance(uuid, str) or not uuid:
        raise ArtifactValidationError(
            f"metadata.json declares no usable uuid: {uuid!r}", CATEGORY_METADATA
        )
    return uuid


def pair_archives(args: list[str]) -> tuple[dict[str, Path], list[tuple[str, str, str]]]:
    """Resolve ``args`` into a ``{uuid: path}`` map for :func:`validate_all`.

    Each argument is either ``path/to.zip`` — whose contract is resolved from
    the UUID the archive itself declares — or an explicit ``uuid=path`` pair for
    a caller that wants to assert the pairing. Positional order is never
    significant, so the documented ``*.zip`` glob works whatever order the shell
    expands it in.

    Returns the map plus a list of ``(subject, category, message)`` problems for
    archives that could not be paired at all.
    """
    pairs: dict[str, Path] = {}
    problems: list[tuple[str, str, str]] = []
    for arg in args:
        uuid: str | None = None
        raw = arg
        # Only treat "=" as a pairing separator when the left side looks like an
        # extension UUID, so a path containing "=" is still usable.
        if "=" in arg:
            head, _, tail = arg.partition("=")
            if "@" in head and tail:
                uuid, raw = head, tail
        path = Path(raw)
        if uuid is None:
            try:
                uuid = read_archive_uuid(path)
            except ArtifactValidationError as exc:
                problems.append((str(path), exc.category, str(exc)))
                continue
        if uuid in pairs:
            problems.append((
                str(path),
                CATEGORY_HARNESS,
                f"{uuid} staged twice: {pairs[uuid]} and {path}",
            ))
            continue
        pairs[uuid] = path
    return pairs, problems


def main(argv: list[str] | None = None) -> int:
    """CLI gate: validate staged ZIPs against the canonical contracts.

    Usage: ``python -m tests.shared.gnome_extensions_artifacts path/to/*.zip``
    or ``... <uuid>=path/to.zip ...``. Each archive is matched to its contract
    by the UUID its own ``metadata.json`` declares, so glob order never matters
    and an ordering mistake in the harness can never be misattributed to an
    extension. Every canonical extension must be supplied exactly once; a
    missing one is reported as a ``harness`` failure.

    Prints a per-extension line carrying the contract identity (revision, UUID,
    package recipe, pinned hash) and, on failure, the :func:`classify` category
    so infra faults are separable from extension faults. Exits non-zero if any
    check fails.
    """
    import sys

    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(
            f"usage: {sys.argv[0]} <zip>... (one per canonical extension; "
            f"each may also be given as <uuid>=<zip>)",
            file=sys.stderr,
        )
        return 2

    pairs, problems = pair_archives(args)

    failures = 0
    for subject, category, message in problems:
        print(f"[FAIL/{category}] {subject}")
        print(f"        {message}")
        failures += 1

    expected = {c.uuid for c in CANONICAL_CONTRACTS}
    for uuid in sorted(set(pairs) - expected):
        print(f"[FAIL/{CATEGORY_METADATA}] {pairs[uuid]}")
        print(f"        archive declares {uuid!r}, which has no canonical contract")
        failures += 1
        del pairs[uuid]

    for contract in CANONICAL_CONTRACTS:
        zip_path = pairs.get(contract.uuid)
        if zip_path is None:
            print(f"[FAIL/{CATEGORY_HARNESS}] {contract.identity}")
            print("        no staged archive declares this UUID")
            failures += 1
            continue
        result = validate_extension_zip(zip_path, contract)
        category = classify(result)
        status = "OK" if result.valid else f"FAIL/{category}"
        print(f"[{status}] {contract.identity} <- {zip_path}")
        if not result.valid:
            failures += 1
            for error in result.errors:
                print(f"        {error}")

    checked = len(CANONICAL_CONTRACTS) + len(problems)
    print(f"{max(checked - failures, 0)}/{checked} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
