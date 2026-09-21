"""Local evidence and cooperative locks; neither is a security sandbox."""
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile


@contextmanager
def job_lock(workspace, session_id):
    # Persistent inodes: unlinking a lock on release creates an acquisition race.
    root = Path(tempfile.gettempdir()) / f"token-saver-locks-{os.getuid()}"
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("unsafe lock directory")
    with ExitStack() as stack:
        keys = ["workspace:" + str(workspace.resolve()), "session:" + session_id]
        for key in sorted(keys):
            path = root / hashlib.sha256(key.encode()).hexdigest()
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            stream = stack.enter_context(os.fdopen(fd, "r+"))
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("workspace or session already has an active Token Saver job") from exc
        yield


def allowed_paths(values):
    if values is None:
        return None
    result = []
    for value in values:
        path = PurePosixPath(value)
        if (not value or value in (".", "./") or path.is_absolute() or
                ".." in path.parts or "\\" in value or any(c in value for c in "*?[]") or
                ".git" in path.parts):
            raise ValueError("allowed paths must be explicit repository-relative files or directories ending in /; no globs or traversal")
        result.append(str(path) + ("/" if value.endswith("/") else ""))
    return result


def _git(workspace, *args):
    result = subprocess.run(["git", "-C", str(workspace), *args], capture_output=True,
                            timeout=30, check=False)
    if result.returncode:
        raise ValueError("Git evidence unavailable: " + result.stderr.decode(errors="replace")[-300:])
    return result.stdout


def snapshot(workspace):
    try:
        root = Path(os.fsdecode(_git(workspace, "rev-parse", "--show-toplevel")).strip())
        revision = _git(root, "rev-parse", "HEAD").decode().strip()
        records = iter(_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").split(b"\0"))
        paths, untracked = {}, []
        for record in records:
            if not record:
                continue
            status, name = record[:2].decode(), os.fsdecode(record[3:])
            paths[name] = status
            if "R" in status or "C" in status:
                paths[os.fsdecode(next(records))] = "rename-source"
            if status == "??":
                untracked.append(name)
        signatures = {}
        for name, status in paths.items():
            path = root / name
            if any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
                raise ValueError("cannot safely inspect a changed path through a symlinked directory")
            digest = hashlib.sha256()
            if path.is_symlink():
                digest.update(os.fsencode(os.readlink(path)))
            elif path.is_file():
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(65536), b""):
                        digest.update(chunk)
            else:
                digest.update(b"absent-or-directory")
            index = _git(root, "ls-files", "--stage", "-z", "--", name)
            signatures[name] = [status, digest.hexdigest(), hashlib.sha256(index).hexdigest(),
                                path.lstat().st_mode if path.exists() or path.is_symlink() else None]
        return {"available": True, "root": str(root), "revision": revision,
                "files": signatures, "untracked_files": sorted(untracked)}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": str(exc), "revision": None, "files": {}}


def change_summary(workspace, before, after, allowed, mode):
    result = {"available": before["available"] and after["available"],
              "base_revision": before.get("revision"), "final_revision": after.get("revision"),
              "allowed_paths": allowed, "scope_checked": False, "scope_violations": [],
              "preexisting_files": sorted(before["files"]),
              "untracked_files": after.get("untracked_files", [])}
    if not result["available"]:
        result["reason"] = before.get("reason") or after.get("reason")
        return result
    touched = {name for name in before["files"].keys() | after["files"].keys()
               if before["files"].get(name) != after["files"].get(name)}
    result["head_changed"] = before["revision"] != after["revision"]
    if result["head_changed"]:
        try:
            touched.update(os.fsdecode(p) for p in _git(workspace, "diff", "--name-only", "--no-renames", "-z",
                                                      before["revision"], after["revision"]).split(b"\0") if p)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            result.update(available=False, reason=str(exc))
    result["changed_files"] = sorted(touched)
    result["scope_checked"] = result["available"] and (allowed is not None or mode == "read")
    if result["scope_checked"]:
        result["scope_violations"] = sorted(name for name in touched if mode == "read" or not any(
            name.startswith(rule) if rule.endswith("/") else name == rule for rule in allowed))
    return result


def configuration(requested, observed):
    fields = ("model", "reasoning_effort")
    matches = {key: (requested[key] == observed.get(key)
                     if requested.get(key) is not None and observed.get(key) is not None else None)
               for key in fields}
    specified = [key for key in fields if requested.get(key) is not None]
    matched = (False if any(matches[key] is False for key in specified) else
               True if specified and all(matches[key] is True for key in specified) else None)
    return {"requested": requested, "observed": {key: observed.get(key) for key in fields},
            "matches": matches, "matches_requested": matched}
