#!/usr/bin/env python3
"""SELinux qualification helpers for the e2e QEMU guest.

The e2e workflow boots the candidate image with SELinux enforcing. These
helpers keep that honest:

``expected-mode DEPLOY``
    Decide from the installed deployment whether enforcing is expected.
    Any deployment that ships an SELinux policy store must run enforcing;
    images without one (e.g. freedesktop-sdk based) report ``unsupported``.

``unlabeled --root R [--exclude FILE] PATH...``
    List paths under PATH that carry no ``security.selinux`` xattr. Taken
    once before the harness injects files (baseline: candidate-owned) and
    once after, so only harness-created files get relabeled.

``check-mode EXPECTED OBSERVED``
    Fail unless ``getenforce`` output matches the expected mode.

``gate LOG --allowlist YAML --json OUT``
    Fail on enforced AVC denials that the allowlist does not name.

``canary BEFORE AFTER --allowlist YAML [--diagnostics FILE] --json OUT``
    Prove a deliberately denied operation shows up in the collected log
    and makes ``gate`` fail. ``--diagnostics`` takes the ``key=value``
    output of ``scripts/selinux_canary.sh``; on failure it says whether the
    canary could not run or ran but was not collected.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SELINUX_XATTR = "security.selinux"
CANARY_TYPE = "httpd_t"
# systemd's EXIT_EXEC: execve failed, here because the policy denied it.
EXIT_EXEC = "203"

_AUDIT_ID = re.compile(r"audit\((\d+\.\d+:\d+)\)")
_DENIED = re.compile(r"avc:\s+denied\s+\{\s*([^}]*?)\s*\}")
_FIELD = re.compile(r"\b(scontext|tcontext|tclass|permissive|comm)=(\"[^\"]*\"|\S+)")


# ── expected mode ────────────────────────────────────────────────────────────


def read_selinux_config(deploy: Path) -> dict[str, str]:
    config = deploy / "etc" / "selinux" / "config"
    values: dict[str, str] = {}
    if not config.is_file():
        return values
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"')
    return values


def expected_mode(deploy: Path) -> tuple[str, str]:
    """Return (mode, policy). mode is ``enforcing`` or ``unsupported``.

    A shipped policy store means enforcing is required, even when the
    candidate's config asks for permissive/disabled: that is a candidate
    defect the runtime check must surface, not a reason to relax.
    """
    config = read_selinux_config(deploy)
    policy = config.get("SELINUXTYPE", "targeted") or "targeted"
    contexts = deploy / "etc" / "selinux" / policy / "contexts" / "files" / "file_contexts"
    if contexts.is_file():
        return "enforcing", policy
    return "unsupported", "-"


# ── labeling ─────────────────────────────────────────────────────────────────


def has_label(path: str) -> bool:
    try:
        return bool(os.getxattr(path, SELINUX_XATTR, follow_symlinks=False))
    except OSError:
        return False


def iter_tree(path: str):
    if not os.path.lexists(path):
        return
    yield path
    if os.path.isdir(path) and not os.path.islink(path):
        for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
            for name in dirnames + filenames:
                yield os.path.join(dirpath, name)


def unlabeled(root: str, paths: list[str], exclude: set[str]) -> list[str]:
    root = root.rstrip("/") or "/"
    found = set()
    for top in paths:
        if not (top == root or top.startswith(root + "/")):
            raise ValueError(f"{top} is not under root {root}")
        for path in iter_tree(top):
            if path not in exclude and not has_label(path):
                found.add(path)
    return sorted(found)


# ── AVC parsing and gate ─────────────────────────────────────────────────────


def selinux_type(context: str) -> str:
    parts = context.split(":")
    return parts[2] if len(parts) >= 3 else context


def parse_denials(text: str) -> list[dict]:
    denials: dict[str, dict] = {}
    for line in text.splitlines():
        match = _DENIED.search(line)
        if not match:
            continue
        fields = {k: v.strip('"') for k, v in _FIELD.findall(line[match.end():])}
        if "scontext" not in fields or "tcontext" not in fields:
            continue
        audit_id = _AUDIT_ID.search(line)
        denial = {
            "audit_id": audit_id.group(1) if audit_id else "",
            "permissions": sorted(match.group(1).split()),
            "scontext": fields["scontext"],
            "tcontext": fields["tcontext"],
            "tclass": fields.get("tclass", ""),
            "comm": fields.get("comm", ""),
            "permissive": fields.get("permissive", "0") == "1",
        }
        # Records without an audit serial (journald's audit transport under
        # `-o cat`) are keyed by their text, which carries a unique pid.
        denial["key"] = "|".join(
            [denial["audit_id"] or line.strip(), " ".join(denial["permissions"]),
             denial["scontext"], denial["tcontext"], denial["tclass"]]
        )
        denials.setdefault(denial["key"], denial)
    return list(denials.values())


def load_allowlist(path: Path) -> list[dict]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("allowed_denials") or []
    required = ("source_context", "target_context", "permission", "comm", "reason")
    for index, entry in enumerate(entries):
        missing = [key for key in required if not str(entry.get(key, "")).strip()]
        if missing:
            raise ValueError(f"allowlist entry {index} is missing {', '.join(missing)}")
    return entries


def _perms(value) -> list[str]:
    if isinstance(value, list):
        return sorted(str(v) for v in value)
    return sorted(str(value).split())


def allowed_by(denial: dict, entries: list[dict]) -> dict | None:
    for entry in entries:
        if selinux_type(entry["source_context"]) != selinux_type(denial["scontext"]):
            continue
        if selinux_type(entry["target_context"]) != selinux_type(denial["tcontext"]):
            continue
        if _perms(entry["permission"]) != denial["permissions"]:
            continue
        if entry["comm"] != denial["comm"]:
            continue
        if entry.get("tclass") and entry["tclass"] != denial["tclass"]:
            continue
        return entry
    return None


def evaluate(text: str, entries: list[dict]) -> dict:
    unexpected, allowed, permissive = [], [], []
    for denial in parse_denials(text):
        entry = allowed_by(denial, entries)
        if entry is not None:
            allowed.append({**denial, "reason": entry["reason"]})
        elif denial["permissive"]:
            permissive.append(denial)
        else:
            unexpected.append(denial)
    return {
        "passed": not unexpected,
        "unexpected": unexpected,
        "allowed": allowed,
        "permissive_domain": permissive,
    }


def describe(denial: dict) -> str:
    return (
        f"{{ {' '.join(denial['permissions'])} }} comm={denial['comm'] or '?'} "
        f"{selinux_type(denial['scontext'])} -> {selinux_type(denial['tcontext'])}"
        f":{denial['tclass']}"
    )


def canary_result(
    before: str, after: str, entries: list[dict], types: tuple[str, ...] = (CANARY_TYPE,)
) -> dict:
    seen = {d["key"] for d in parse_denials(before)}
    new = [
        d
        for d in parse_denials(after)
        if d["key"] not in seen
        and {selinux_type(d["scontext"]), selinux_type(d["tcontext"])} & set(types)
    ]
    verdict = evaluate(after, entries)
    detected = bool(new) and any(d in verdict["unexpected"] for d in new)
    return {"detected": detected, "canary_denials": new, "gate_failed": not verdict["passed"]}


def parse_diagnostics(text: str) -> dict[str, str]:
    """Read the ``key=value`` lines printed by ``selinux_canary.sh``."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and re.fullmatch(r"[a-z][a-z0-9_]*", key):
            values[key] = value.strip()
    return values


def canary_types(diagnostics: dict[str, str]) -> tuple[str, ...]:
    """Every domain the canary tried, so a denial in any of them counts."""
    types = [key[len("attempt_"):] for key in diagnostics if key.startswith("attempt_")]
    chosen = diagnostics.get("canary_type", "")
    if chosen and chosen != "none" and chosen not in types:
        types.append(chosen)
    return tuple(types) or (CANARY_TYPE,)


def _collection_evidence(diagnostics: dict[str, str]) -> str:
    keys = ("audit_log", "auditd", "journal_kernel_avc", "journal_avc", "dmesg_avc",
            "collector_context")
    return ", ".join(f"{key}={diagnostics.get(key) or '?'}" for key in keys)


def canary_failure(result: dict, diagnostics: dict[str, str] | None) -> tuple[str, str]:
    """Return (reason, message) for a canary that did not reach the gate.

    reason is ``not-run`` (no denial was produced), ``not-collected`` (a
    denial was produced but no log the collector reads has it),
    ``permissive`` or ``allowlisted`` (collected but did not fail the gate),
    or ``unknown`` when no diagnostics were supplied.
    """
    denials = result["canary_denials"]
    if denials:
        if all(d["permissive"] for d in denials):
            return "permissive", (
                f"its denial was collected but the domain is permissive "
                f"({describe(denials[0])}), so the operation was not blocked"
            )
        return "allowlisted", (
            f"its denial was collected but selinux_allowlist.yaml matches it "
            f"({describe(denials[0])}); an entry that broad hides real denials"
        )
    if diagnostics is None:
        return "unknown", (
            "no canary diagnostics were supplied, so it is unknown whether the canary "
            "ran or its denial was not collected"
        )
    if "canary_type" not in diagnostics:
        return "not-run", (
            "the canary could not run: the guest returned no canary diagnostics "
            f"(ssh/sudo exit {diagnostics.get('canary_ssh_rc') or '?'})"
        )
    if diagnostics.get("collect_rc", "0") != "0":
        return "not-collected", (
            f"the canary ran but the AVC collector failed (exit {diagnostics['collect_rc']})"
        )
    status = diagnostics.get("canary_status", "none")
    rc = diagnostics.get("canary_rc", "none")
    if status != EXIT_EXEC and not (status == "none" and rc == EXIT_EXEC):
        tried = ", ".join(canary_types(diagnostics))
        return "not-run", (
            f"the canary could not run: no candidate domain ({tried}) was blocked at "
            f"execve, so no denial was produced. Last attempt "
            f"{diagnostics.get('canary_type')}: systemd-run exit {rc}, unit status "
            f"{status}: {diagnostics.get('canary_stderr') or 'no output'}. "
            f"seinfo: {diagnostics.get('seinfo_httpd_t') or '?'}"
        )
    return "not-collected", (
        f"the canary ran and was blocked ({diagnostics.get('canary_type')}, status "
        f"{EXIT_EXEC}/EXEC) but its denial was not collected: "
        f"{_collection_evidence(diagnostics)}. Either denials do not reach the audit "
        f"log, journal or kernel ring buffer, or the policy dontaudits this access "
        f"({diagnostics.get('sesearch_dontaudit') or 'sesearch unavailable'})"
    )


# ── CLI ──────────────────────────────────────────────────────────────────────


def _write_json(path: str | None, payload: dict) -> None:
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("expected-mode")
    p.add_argument("deploy", type=Path)

    p = sub.add_parser("unlabeled")
    p.add_argument("--root", required=True)
    p.add_argument("--exclude", type=Path)
    p.add_argument("paths", nargs="+")

    p = sub.add_parser("check-mode")
    p.add_argument("expected")
    p.add_argument("observed")

    p = sub.add_parser("gate")
    p.add_argument("log", type=Path)
    p.add_argument("--allowlist", type=Path, required=True)
    p.add_argument("--json")

    p = sub.add_parser("canary")
    p.add_argument("before", type=Path)
    p.add_argument("after", type=Path)
    p.add_argument("--allowlist", type=Path, required=True)
    p.add_argument("--diagnostics", type=Path)
    p.add_argument("--json")

    args = parser.parse_args(argv)

    if args.command == "expected-mode":
        mode, policy = expected_mode(args.deploy)
        print(f"{mode} {policy}")
        return 0

    if args.command == "unlabeled":
        exclude = set()
        if args.exclude and args.exclude.is_file():
            exclude = set(args.exclude.read_text(encoding="utf-8").splitlines())
        try:
            for path in unlabeled(args.root, args.paths, exclude):
                print(path)
        except ValueError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "check-mode":
        observed = args.observed.strip()
        if args.expected == "unsupported":
            if observed == "Enforcing":
                print("::error::image ships no SELinux policy store but the guest reports Enforcing")
                return 1
            print(f"SELinux unsupported by this image (guest reports: {observed or 'no getenforce'})")
            return 0
        if observed != "Enforcing":
            print(
                f"::error::SELinux must be Enforcing in the qualification VM; guest reports "
                f"'{observed or 'nothing'}'. A candidate that ships a policy but boots "
                "permissive or disabled fails qualification."
            )
            return 1
        print("SELinux: Enforcing")
        return 0

    try:
        entries = load_allowlist(args.allowlist)
    except (OSError, ValueError) as exc:
        print(f"::error::invalid SELinux allowlist: {exc}")
        return 2

    if args.command == "gate":
        verdict = evaluate(args.log.read_text(encoding="utf-8", errors="replace"), entries)
        _write_json(args.json, verdict)
        for denial in verdict["allowed"]:
            print(f"allowlisted: {describe(denial)} ({denial['reason']})")
        for denial in verdict["permissive_domain"]:
            print(f"::warning::AVC in permissive domain (not blocked): {describe(denial)}")
        for denial in verdict["unexpected"]:
            print(f"::error::unexpected SELinux denial: {describe(denial)}")
        print(
            f"AVC gate: {len(verdict['unexpected'])} unexpected, {len(verdict['allowed'])} "
            f"allowlisted, {len(verdict['permissive_domain'])} permissive-domain"
        )
        return 0 if verdict["passed"] else 1

    diagnostics = None
    if args.diagnostics is not None:
        diagnostics = {}
        if args.diagnostics.is_file():
            diagnostics = parse_diagnostics(
                args.diagnostics.read_text(encoding="utf-8", errors="replace")
            )
    types = canary_types(diagnostics or {})
    result = canary_result(
        args.before.read_text(encoding="utf-8", errors="replace"),
        args.after.read_text(encoding="utf-8", errors="replace"),
        entries,
        types,
    )
    result["canary_types"] = list(types)
    if diagnostics is not None:
        result["diagnostics"] = diagnostics
    if not result["detected"]:
        reason, message = canary_failure(result, diagnostics)
        result["reason"] = reason
        _write_json(args.json, result)
        print(
            f"::error::SELinux canary did not reach the AVC gate ({reason}): {message}. "
            "A clean gate proves nothing until the canary is seen."
        )
        return 1
    result["reason"] = "detected"
    _write_json(args.json, result)
    for denial in result["canary_denials"]:
        print(f"canary denial detected: {describe(denial)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
