"""Build the complete commercial release through a guarded staging directory."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BLENDER_AUTOMATION = REPOSITORY_ROOT / "automation" / "blender"
if str(BLENDER_AUTOMATION) not in sys.path:
    sys.path.insert(0, str(BLENDER_AUTOMATION))

from common import (  # noqa: E402
    display_path,
    load_json,
    require_build_path,
    resolve_from_repository,
    write_json_atomic,
    write_text_atomic,
)


BUILD_ROOT = (REPOSITORY_ROOT / "build").resolve()
DIST_ROOT = (REPOSITORY_ROOT / "dist").resolve()
REPORT_PATH = BUILD_ROOT / "release_build_report.json"

IGNORED_NAMES = {
    ".DS_Store",
    ".git",
    "__pycache__",
    "node_modules",
}
IGNORED_SUFFIXES = {
    ".blend1",
    ".blend2",
    ".blend3",
    ".blend@",
    ".blend~",
    ".pyc",
    ".pyo",
}

REQUIRED_SCRIPTS = (
    "automation/blender/validate_assets.py",
    "automation/blender/export_assets.py",
    "automation/blender/render_previews.py",
    "automation/blender/render_collection_overviews.py",
    "automation/scripts/generate_docs.py",
)


class ReleaseBuildError(RuntimeError):
    """A release prerequisite or pipeline stage failed."""


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the complete asset release")
    parser.add_argument(
        "--config",
        default="automation/config/release_config.json",
        help="Release config path, relative to the repository root",
    )
    parser.add_argument(
        "--blender",
        help="Blender executable; defaults to BLENDER_BIN, PATH, or the standard macOS app",
    )
    parser.add_argument(
        "--license",
        help="Approved license file override; the default comes from release config",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Check every required input without clearing build output or running tools",
    )
    return parser.parse_args(argv)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repository_path(path_text: str) -> Path:
    return resolve_from_repository(path_text)


def require_inside(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ReleaseBuildError(f"{label} must be inside {root}") from error


def release_settings(config: Dict[str, Any]) -> Dict[str, str]:
    settings = config.get("release")
    if not isinstance(settings, dict):
        raise ReleaseBuildError("Config must contain a release object")

    required = {
        "package_name",
        "version",
        "source_blend",
        "textures_directory",
        "license_file",
        "third_party_notices",
        "threejs_example",
    }
    missing = sorted(required - set(settings))
    if missing:
        raise ReleaseBuildError(f"Release config is missing: {', '.join(missing)}")

    result = {name: str(settings[name]).strip() for name in required}
    if any(not value for value in result.values()):
        raise ReleaseBuildError("Release config values must not be empty")
    for field in ("package_name", "version"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", result[field]):
            raise ReleaseBuildError(
                f"release.{field} may contain only letters, numbers, dots, underscores, and hyphens"
            )
    return result


def find_blender(explicit: Optional[str]) -> Optional[Path]:
    candidates = [
        explicit,
        os.environ.get("BLENDER_BIN"),
        shutil.which("blender"),
        "/Applications/Blender.app/Contents/MacOS/Blender",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser().resolve()
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def preflight(
    config_path: Path,
    settings: Dict[str, str],
    blender_override: Optional[str],
    license_override: Optional[str],
) -> Tuple[List[str], Dict[str, Path]]:
    errors: List[str] = []
    source_blend = repository_path(settings["source_blend"])
    textures_directory = repository_path(settings["textures_directory"])
    threejs_example = repository_path(settings["threejs_example"])
    license_path = repository_path(license_override or settings["license_file"])
    third_party_notices = repository_path(settings["third_party_notices"])
    blender_path = find_blender(blender_override)
    npm_path_text = shutil.which("npm")
    npm_path = Path(npm_path_text).resolve() if npm_path_text else None

    required_files = {
        "Configuration": config_path,
        "Blender source": source_blend,
        "Approved license": license_path,
        "Third-party notices": third_party_notices,
        "Three.js package manifest": threejs_example / "package.json",
        "Three.js lockfile": threejs_example / "package-lock.json",
    }
    for script in REQUIRED_SCRIPTS:
        required_files[f"Automation script {script}"] = REPOSITORY_ROOT / script

    for label, path in required_files.items():
        if not path.is_file():
            errors.append(f"{label} is missing: {display_path(path)}")

    if not textures_directory.is_dir():
        errors.append(f"Texture source directory is missing: {display_path(textures_directory)}")
    if not threejs_example.is_dir():
        errors.append(f"Three.js example directory is missing: {display_path(threejs_example)}")
    if blender_path is None:
        errors.append("Blender executable was not found; use --blender or BLENDER_BIN")
    if npm_path is None:
        errors.append("npm executable was not found on PATH")

    final_name = f"{settings['package_name']}_v{settings['version']}"
    final_directory = (DIST_ROOT / final_name).resolve()
    final_zip = (DIST_ROOT / f"{final_name}.zip").resolve()
    require_inside(final_directory, DIST_ROOT, "Release directory")
    require_inside(final_zip, DIST_ROOT, "Release ZIP")
    if final_directory.exists() and not final_directory.is_dir():
        errors.append(f"Release directory path is not a directory: {display_path(final_directory)}")
    if final_zip.exists() and not final_zip.is_file():
        errors.append(f"Release ZIP path is not a file: {display_path(final_zip)}")

    paths = {
        "source_blend": source_blend,
        "textures_directory": textures_directory,
        "threejs_example": threejs_example,
        "license": license_path,
        "third_party_notices": third_party_notices,
        "blender": blender_path or Path("blender"),
        "npm": npm_path or Path("npm"),
        "final_directory": final_directory,
        "final_zip": final_zip,
    }
    return errors, paths


def build_report(status: str, settings: Dict[str, str]) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "status": status,
        "release": {
            "package_name": settings["package_name"],
            "version": settings["version"],
        },
        "steps": [],
        "outputs": {},
        "errors": [],
    }


def record_step(report: Dict[str, Any], name: str, status: str, **details: Any) -> None:
    step = {"name": name, "status": status}
    step.update(details)
    report["steps"].append(step)


def run_command(
    report: Dict[str, Any],
    name: str,
    command: Sequence[str],
    cwd: Path = REPOSITORY_ROOT,
) -> None:
    print(f"\n==> {name}", flush=True)
    result = subprocess.run(list(command), cwd=str(cwd), check=False)
    if result.returncode != 0:
        record_step(report, name, "error", exit_code=result.returncode)
        raise ReleaseBuildError(f"{name} failed with exit code {result.returncode}")
    record_step(report, name, "pass", exit_code=0)


def load_pass_report(path: Path, label: str, allowed_statuses: Iterable[str] = ("pass",)) -> Dict[str, Any]:
    if not path.is_file():
        raise ReleaseBuildError(f"{label} did not produce {display_path(path)}")
    data = load_json(path)
    allowed = set(allowed_statuses)
    if data.get("status") not in allowed:
        raise ReleaseBuildError(f"{label} report status is {data.get('status')!r}")
    return data


def clear_build_directory() -> None:
    if BUILD_ROOT != (REPOSITORY_ROOT / "build").resolve():
        raise ReleaseBuildError("Refusing to clear an unexpected build directory")
    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    BUILD_ROOT.mkdir(parents=True)


def ignored_copy_names(_directory: str, names: List[str]) -> List[str]:
    ignored = []
    for name in names:
        if name in IGNORED_NAMES or any(name.endswith(suffix) for suffix in IGNORED_SUFFIXES):
            ignored.append(name)
    return ignored


def ensure_no_symlinks(path: Path, label: str) -> None:
    candidates = [path] if path.is_symlink() else []
    if path.is_dir():
        candidates.extend(item for item in path.rglob("*") if item.is_symlink())
    if candidates:
        shown = ", ".join(display_path(item) for item in candidates[:3])
        raise ReleaseBuildError(f"{label} contains unsupported symbolic links: {shown}")


def copy_tree(source: Path, destination: Path, label: str) -> None:
    ensure_no_symlinks(source, label)
    shutil.copytree(source, destination, ignore=ignored_copy_names)


def category_counts(assets: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for asset in assets:
        category = str(asset["category"])
        counts[category] = counts.get(category, 0) + 1
    return counts


def create_release_summary(
    staging: Path,
    settings: Dict[str, str],
    manifest: Dict[str, Any],
    validation: Dict[str, Any],
) -> None:
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ReleaseBuildError("Manifest has no assets for the release summary")

    counts = category_counts(assets)
    total_glb_size = sum(int(asset["glb_size_bytes"]) for asset in assets)
    summary = {
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "status": "pass",
        "package_name": settings["package_name"],
        "version": settings["version"],
        "asset_count": len(assets),
        "category_counts": counts,
        "combined_glb_size_bytes": total_glb_size,
        "validation": {
            "status": validation.get("status"),
            "error_count": validation.get("summary", {}).get("error_count"),
            "warning_count": validation.get("summary", {}).get("warning_count"),
        },
        "included_directories": [
            "Blender",
            "GLB",
            "Textures",
            "Manifest",
            "Preview",
            "ThreeJS_Example",
            "Documentation",
        ],
    }
    write_json_atomic(staging / "RELEASE_SUMMARY.json", summary)

    category_text = ", ".join(f"{count} {name}" for name, count in counts.items())
    notes = (
        f"# {settings['package_name']} v{settings['version']}\n\n"
        "This release was assembled by the repository's validated release pipeline.\n\n"
        "## Contents\n\n"
        f"- {len(assets)} buildings: {category_text}\n"
        "- Blender catalogue source\n"
        "- Individual self-contained GLB files\n"
        "- Source texture atlases\n"
        "- Individual and collection preview renders\n"
        "- JSON and CSV asset manifests\n"
        "- Three.js compatibility example\n"
        "- Product documentation, license, third-party notices, and AI disclosure\n\n"
        "See `Documentation/README.md` for asset details and usage notes.\n"
    )
    write_text_atomic(staging / "RELEASE_NOTES.md", notes)


def stage_release(
    staging: Path,
    settings: Dict[str, str],
    paths: Dict[str, Path],
    threejs_work: Path,
    manifest: Dict[str, Any],
    validation: Dict[str, Any],
) -> None:
    release_root = BUILD_ROOT / "release"
    required_generated = {
        "GLB": release_root / "GLB",
        "Manifest": release_root / "Manifest",
        "Preview": release_root / "Preview",
        "Documentation": release_root / "Documentation",
    }
    for label, source in required_generated.items():
        if not source.is_dir():
            raise ReleaseBuildError(f"Generated {label} directory is missing")
        copy_tree(source, staging / label, f"Generated {label}")

    ensure_no_symlinks(paths["source_blend"], "Blender source")
    blender_directory = staging / "Blender"
    blender_directory.mkdir()
    shutil.copy2(paths["source_blend"], blender_directory / paths["source_blend"].name)

    copy_tree(paths["textures_directory"], staging / "Textures", "Texture sources")
    copy_tree(threejs_work, staging / "ThreeJS_Example", "Three.js example")
    shutil.copy2(paths["license"], staging / "Documentation" / "LICENSE.txt")
    shutil.copy2(
        paths["third_party_notices"],
        staging / "Documentation" / "THIRD_PARTY_NOTICES.txt",
    )
    create_release_summary(staging, settings, manifest, validation)


def create_zip(source: Path, destination: Path, archive_root: str) -> None:
    with zipfile.ZipFile(
        destination,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ReleaseBuildError(f"Refusing to archive symbolic link {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            archive.write(path, (Path(archive_root) / relative).as_posix())
    if destination.stat().st_size <= 0:
        raise ReleaseBuildError("ZIP creation produced an empty file")


def replace_outputs_atomically(
    staging: Path,
    temporary_zip: Path,
    final_directory: Path,
    final_zip: Path,
) -> None:
    token = uuid.uuid4().hex
    directory_backup = DIST_ROOT / f".{final_directory.name}.{token}.backup"
    zip_backup = DIST_ROOT / f".{final_zip.name}.{token}.backup"
    moved_directory = False
    moved_zip = False
    installed_directory = False
    installed_zip = False

    try:
        if final_directory.exists():
            os.replace(final_directory, directory_backup)
            moved_directory = True
        if final_zip.exists():
            os.replace(final_zip, zip_backup)
            moved_zip = True

        os.replace(staging, final_directory)
        installed_directory = True
        os.replace(temporary_zip, final_zip)
        installed_zip = True
    except Exception:
        if installed_zip and final_zip.exists():
            final_zip.unlink()
        if installed_directory and final_directory.exists():
            shutil.rmtree(final_directory)
        if moved_zip and zip_backup.exists():
            os.replace(zip_backup, final_zip)
        if moved_directory and directory_backup.exists():
            os.replace(directory_backup, final_directory)
        raise
    else:
        if directory_backup.exists():
            shutil.rmtree(directory_backup)
        if zip_backup.exists():
            zip_backup.unlink()


def blender_command(blender: Path, source_blend: Path, script: str, config_path: Path) -> List[str]:
    return [
        str(blender),
        "--background",
        str(source_blend),
        "--python-exit-code",
        "2",
        "--python",
        str(REPOSITORY_ROOT / script),
        "--",
        "--config",
        str(config_path),
    ]


def run_pipeline(
    report: Dict[str, Any],
    config_path: Path,
    settings: Dict[str, str],
    paths: Dict[str, Path],
) -> None:
    clear_build_directory()
    record_step(report, "clear temporary build", "pass")

    validation_command = blender_command(
        paths["blender"], paths["source_blend"], REQUIRED_SCRIPTS[0], config_path
    ) + ["--fail-on-errors"]
    run_command(report, "validate Blender source", validation_command)
    validation = load_pass_report(
        BUILD_ROOT / "validation_report.json",
        "Validation",
        allowed_statuses=("pass", "warning"),
    )

    run_command(
        report,
        "export GLBs and manifest",
        blender_command(paths["blender"], paths["source_blend"], REQUIRED_SCRIPTS[1], config_path),
    )
    load_pass_report(BUILD_ROOT / "export_report.json", "Export")
    manifest = load_json(BUILD_ROOT / "release" / "Manifest" / "asset_manifest.json")

    run_command(
        report,
        "render individual previews",
        blender_command(paths["blender"], paths["source_blend"], REQUIRED_SCRIPTS[2], config_path),
    )
    load_pass_report(BUILD_ROOT / "preview_report.json", "Preview rendering")

    run_command(
        report,
        "render collection overviews",
        blender_command(paths["blender"], paths["source_blend"], REQUIRED_SCRIPTS[3], config_path),
    )
    load_pass_report(BUILD_ROOT / "overview_report.json", "Overview rendering")

    run_command(
        report,
        "generate documentation",
        [sys.executable, str(REPOSITORY_ROOT / REQUIRED_SCRIPTS[4])],
    )
    load_pass_report(BUILD_ROOT / "documentation_report.json", "Documentation generation")

    threejs_work = BUILD_ROOT / "threejs_work"
    copy_tree(paths["threejs_example"], threejs_work, "Three.js example source")
    run_command(
        report,
        "install Three.js dependencies",
        [str(paths["npm"]), "ci", "--no-audit", "--no-fund"],
        cwd=threejs_work,
    )
    run_command(
        report,
        "build Three.js example",
        [str(paths["npm"]), "run", "build"],
        cwd=threejs_work,
    )
    shutil.rmtree(threejs_work / "node_modules")

    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".release-staging-", dir=str(DIST_ROOT)))
    temporary_zip = DIST_ROOT / f".{paths['final_zip'].name}.{uuid.uuid4().hex}.tmp"
    try:
        stage_release(staging, settings, paths, threejs_work, manifest, validation)
        record_step(report, "stage release contents", "pass")
        create_zip(staging, temporary_zip, paths["final_directory"].name)
        record_step(report, "create release ZIP", "pass")
        replace_outputs_atomically(
            staging,
            temporary_zip,
            paths["final_directory"],
            paths["final_zip"],
        )
        record_step(report, "publish generated outputs", "pass")
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if temporary_zip.exists():
            temporary_zip.unlink()

    report["outputs"] = {
        "directory": display_path(paths["final_directory"]),
        "zip": display_path(paths["final_zip"]),
        "zip_size_bytes": paths["final_zip"].stat().st_size,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        config_path = repository_path(arguments.config)
        config = load_json(config_path)
        settings = release_settings(config)
    except Exception as error:
        print(f"Release preflight failed: {error}", file=sys.stderr)
        return 1

    report = build_report("running", settings)
    try:
        require_build_path(REPORT_PATH, "Release build report")
        errors, paths = preflight(
            config_path,
            settings,
            arguments.blender,
            arguments.license,
        )
        if errors:
            report["status"] = "error"
            report["errors"] = errors
            record_step(report, "preflight", "error", errors=errors)
            write_json_atomic(REPORT_PATH, report)
            print("Release preflight FAIL:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            print(f"Report: {display_path(REPORT_PATH)}", file=sys.stderr)
            return 1

        record_step(report, "preflight", "pass")
        if arguments.preflight_only:
            report["status"] = "pass"
            write_json_atomic(REPORT_PATH, report)
            print("Release preflight PASS")
            print(f"Report: {display_path(REPORT_PATH)}")
            return 0

        run_pipeline(report, config_path, settings, paths)
        report["status"] = "pass"
        report["generated_at_utc"] = utc_now()
        write_json_atomic(REPORT_PATH, report)
        print("\nRelease build PASS")
        print(f"Directory: {report['outputs']['directory']}")
        print(f"ZIP: {report['outputs']['zip']}")
        print(f"Report: {display_path(REPORT_PATH)}")
        return 0
    except Exception as error:
        report["status"] = "error"
        report["generated_at_utc"] = utc_now()
        report["errors"].append(f"{type(error).__name__}: {error}")
        try:
            write_json_atomic(REPORT_PATH, report)
        except Exception:
            pass
        print(f"Release build FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        print(f"Report: {display_path(REPORT_PATH)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
