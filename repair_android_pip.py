"""Repair python-for-android's temporary pip and target-wheel install in WSL/Linux."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

HOST_PYTHON = Path(
    "other_builds/hostpython3/desktop/hostpython3/native-build/root/usr/local/bin/python"
)


def _inside(path, root):
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path is outside the project build cache: {path}")
    return resolved


def find_build_dir(project, requested=None):
    project = Path(project).resolve()
    cache = _inside(project / ".buildozer", project)
    platform = _inside(cache / "android/platform", cache)
    if requested is None:
        candidates = [p for p in platform.glob("build-*/build") if (p / HOST_PYTHON).is_file()]
        if len(candidates) != 1:
            raise ValueError("Expected one compiled build directory; use --build-dir to select it.")
        build = candidates[0]
    else:
        build = Path(requested)
        build = build if build.is_absolute() else project / build
    build = _inside(build, cache)
    if build.name != "build" or not build.parent.name.startswith("build-") or build.parent.parent != platform:
        raise ValueError("--build-dir must select .buildozer/android/platform/build-*/build.")
    native = _inside(build / HOST_PYTHON, cache)
    if not native.is_file():
        raise ValueError(f"Compiled host Python is missing: {native}")
    venv = build / "venv"
    if venv.is_symlink():
        raise ValueError(f"Refusing a symlinked temporary environment: {venv}")
    _inside(venv, cache)
    if venv.exists() and not venv.is_dir():
        raise ValueError(f"Temporary environment is not a directory: {venv}")
    return build, native


def active_builds(project, proc_root=Path("/proc")):
    if not proc_root.is_dir():
        raise RuntimeError("Run this helper in WSL/Linux so active builds can be checked.")
    project = Path(project).resolve()
    found = []
    for process in proc_root.iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            if not (process / "cwd").resolve(strict=True).is_relative_to(project):
                continue
            args = (process / "cmdline").read_bytes().decode(errors="replace").strip("\0").split("\0")
            programs = {Path(arg).name for arg in args[:2]}
            pip_program = any(re.fullmatch(r"pip(?:[0-9]+(?:\.[0-9]+)?)?", name) for name in programs)
            if "buildozer" in programs or pip_program or "pythonforandroid.toolchain" in args or any(
                args[i:i + 2] == ["-m", "pip"] for i in range(len(args) - 1)
            ):
                found.append(process.name)
        except (OSError, ValueError):
            continue
    return found


def _run(arguments, project):
    return subprocess.run(arguments, cwd=project, check=True, capture_output=True, text=True).stdout.strip()


def patch_target_install(build_py, backup_dir):
    """Make the known p4a target-only pip command accept Android wheel tags."""
    source = build_py.read_text(encoding="utf-8")
    target = '"install -v --target \'{0}\' --no-deps -r requirements.txt"'
    addition = (
        '\n                + " " + " ".join("--platform=" + tag for tag in\n'
        '                                 PyProjectRecipe.get_wheel_platform_tags(arch.arch, ctx))'
    )
    patched = target + "\n                # mango-target-wheel-platforms" + addition
    if source.count(patched) == 1 or source.count(target + addition) == 1:
        return False
    if source.count(target) != 1 or "mango-target-wheel-platforms" in source or "PyProjectRecipe" not in source:
        raise ValueError("Unknown p4a target-install command; refusing an automatic source patch.")
    updated = source.replace(target, patched, 1)
    try:
        compile(updated, str(build_py), "exec")
    except SyntaxError as error:
        raise ValueError("The known target-platform patch did not produce valid Python.") from error
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"p4a-build-{uuid4().hex[:12]}.py"
    backup.write_bytes(build_py.read_bytes())
    build_py.write_text(updated, encoding="utf-8")
    print(f"Target-wheel pip command patched; original preserved at {backup}", flush=True)
    return True


def repair(project, requested=None):
    project = Path(project).resolve()
    build, native = find_build_dir(project, requested)
    running = active_builds(project)
    if running:
        raise RuntimeError(f"Build or pip processes are still running (PID {', '.join(running)}); stop them first.")
    version = _run([str(native), "-I", "-c", "import ensurepip; print(ensurepip.version())"], project)
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?", version):
        raise ValueError(f"Invalid bundled pip version: {version!r}")
    cache = project / ".buildozer"
    backups = _inside(cache / "pip-recovery-backups", cache)
    build_py = _inside(cache / "android/platform/python-for-android/pythonforandroid/build.py", cache)
    patch_target_install(build_py, backups)
    venv = build / "venv"
    backup = None
    if venv.exists():
        backup = _inside(backups / f"venv-{uuid4().hex[:12]}", cache)
        if backup.exists():
            raise RuntimeError(f"Backup already exists: {backup}")
        backups.mkdir(parents=True, exist_ok=True)
        venv.rename(backup)
        print(f"Previous temporary environment preserved at {backup}", flush=True)
    _run([str(native), "-I", "-m", "venv", str(venv)], project)
    constraints = venv / "pip-constraints.txt"
    constraints.write_text(f"pip=={version}\n", encoding="utf-8")
    # A file URI also works when a project path contains spaces.
    (venv / "pip.conf").write_text(
        f"[install]\nconstraint = {constraints.as_uri()}\n", encoding="utf-8"
    )
    python = str(venv / "bin/python")
    _inside(Path(python), cache)
    print(_run([python, "-I", "-m", "pip", "--version"], project), flush=True)
    print(_run([python, "-I", "-m", "pip", "check"], project), flush=True)
    inspect = (
        "import json,pip,importlib.metadata as m; "
        "print(json.dumps([pip.__version__,[d.version for d in m.distributions() "
        "if (d.metadata.get('Name') or '').lower()=='pip']]))"
    )
    installed = json.loads(_run([python, "-I", "-c", inspect], project))
    if installed != [version, [version]]:
        raise RuntimeError(f"Unexpected pip installation after repair: {installed!r}")
    print(f"Temporary Android pip repaired and constrained to bundled version {version}.", flush=True)
    return venv, backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--build-dir", type=Path, help="Select one project build directory if several exist.")
    arguments = parser.parse_args(argv)
    try:
        repair(arguments.project_dir, arguments.build_dir)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Android pip repair failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stderr or error.stdout, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
