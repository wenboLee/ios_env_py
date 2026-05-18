#!/usr/bin/env python3
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "main.py"
BUILD_ROOT = ROOT / "build"
DIST_ROOT = ROOT / "dist"
DEFAULT_NAME = "spaceauth-cli"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a standalone executable for the current platform."
    )
    parser.add_argument(
        "--name",
        default=DEFAULT_NAME,
        help="Executable name. Defaults to %(default)s.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove prior build artifacts for the current platform before building.",
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Build a single-file executable instead of a directory bundle.",
    )
    return parser


def detect_platform() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        return "windows", machine
    if system == "darwin":
        return "macos", machine

    raise RuntimeError(
        f"Unsupported platform: {platform.system()}. Only Windows and macOS are supported."
    )


def ensure_pyinstaller() -> None:
    try:
        __import__("PyInstaller")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyInstaller is not installed. Run `pip install -r requirements.txt` first."
        ) from exc


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def main() -> int:
    args = build_parser().parse_args()
    ensure_pyinstaller()

    target_os, target_arch = detect_platform()
    build_dir = BUILD_ROOT / target_os
    dist_dir = DIST_ROOT / target_os
    spec_path = ROOT / f"{args.name}.{target_os}.spec"

    if args.clean:
        for path in (build_dir, dist_dir, spec_path):
            remove_path(path)

    dist_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        args.name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        "--specpath",
        str(ROOT),
        str(ENTRYPOINT),
    ]

    if args.onefile:
        command.append("--onefile")

    print(f"Building {args.name} for {target_os} ({target_arch})")
    print(f"Output directory: {dist_dir}")

    try:
        subprocess.run(command, check=True, cwd=ROOT)
    except subprocess.CalledProcessError as exc:
        print(f"Build failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode

    extension = ".exe" if target_os == "windows" and args.onefile else ""
    artifact = dist_dir / (f"{args.name}{extension}" if args.onefile else args.name)

    print(f"Build completed: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
