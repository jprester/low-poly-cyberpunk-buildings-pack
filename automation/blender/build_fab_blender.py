"""Create a self-contained Blender copy for Fab's primary format upload."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import bpy


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from common import (  # noqa: E402
    display_path,
    require_build_path,
    resolve_from_repository,
    write_json_atomic,
)


REPOSITORY_ROOT = SCRIPT_DIRECTORY.parents[1]
DIST_ROOT = (REPOSITORY_ROOT / "dist").resolve()


def blender_script_arguments() -> Sequence[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a self-contained Blender file for Fab"
    )
    parser.add_argument(
        "--output",
        default="dist/Fab_Formats/Blender/Cyberpunk_Building_Pack_v1.0.blend",
        help="Generated .blend output; it must be inside the repository dist directory",
    )
    parser.add_argument(
        "--report",
        default="build/fab_blender_report.json",
        help="Machine-readable report path; it must be inside build",
    )
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_dist_path(path: Path, label: str) -> None:
    try:
        path.resolve().relative_to(DIST_ROOT)
    except ValueError as error:
        raise ValueError(f"{label} must be inside {DIST_ROOT}") from error


def main() -> int:
    arguments = parse_arguments(blender_script_arguments())
    source_blend = Path(bpy.data.filepath).resolve()
    if not source_blend.is_file():
        raise RuntimeError("Open a saved Blender source file before running this script")

    output_path = resolve_from_repository(arguments.output)
    report_path = resolve_from_repository(arguments.report)
    require_dist_path(output_path, "Fab Blender output")
    require_build_path(report_path, "Fab Blender report")
    if output_path.suffix.lower() != ".blend":
        raise ValueError("Fab Blender output must use the .blend extension")
    if output_path.resolve() == source_blend:
        raise ValueError("Fab Blender output must not overwrite the source file")

    source_hash_before = sha256(source_blend)
    file_images = sorted(
        (image for image in bpy.data.images if image.source == "FILE"),
        key=lambda image: image.name,
    )
    if not file_images:
        raise RuntimeError("The Blender source contains no file-backed images to pack")

    image_records = []
    for image in file_images:
        resolved_path = Path(bpy.path.abspath(image.filepath)).resolve()
        if image.packed_file is None and not resolved_path.is_file():
            raise FileNotFoundError(
                f"Cannot pack missing image {image.name}: {display_path(resolved_path)}"
            )
        image_records.append(
            {
                "name": image.name,
                "source_path": display_path(resolved_path),
                "was_packed": image.packed_file is not None,
            }
        )
        if image.packed_file is None:
            image.pack()

    unpacked = [image.name for image in file_images if image.packed_file is None]
    if unpacked:
        raise RuntimeError(f"Images were not packed: {', '.join(unpacked)}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.parent / (
        f".{output_path.stem}.{uuid.uuid4().hex}.tmp.blend"
    )
    try:
        result = bpy.ops.wm.save_as_mainfile(
            filepath=str(temporary_path),
            check_existing=False,
            compress=True,
            copy=True,
        )
        if "FINISHED" not in result:
            raise RuntimeError(f"Blender save returned {sorted(result)}")
        if not temporary_path.is_file() or temporary_path.stat().st_size <= 0:
            raise RuntimeError("Blender did not produce a valid output file")
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    source_hash_after = sha256(source_blend)
    if source_hash_after != source_hash_before:
        raise RuntimeError("Source Blender file changed while building the Fab copy")

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "source_blend": display_path(source_blend),
        "source_sha256": source_hash_before,
        "output_blend": display_path(output_path),
        "output_size_bytes": output_path.stat().st_size,
        "output_sha256": sha256(output_path),
        "blender_version": bpy.app.version_string,
        "file_image_count": len(file_images),
        "packed_image_count": sum(
            1 for image in file_images if image.packed_file is not None
        ),
        "images": image_records,
    }
    write_json_atomic(report_path, report)
    print(
        f"Fab Blender PASS: {report['packed_image_count']} images packed into "
        f"{display_path(output_path)}"
    )
    print(f"Fab Blender report: {display_path(report_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
