"""Export each validated building as an individual, origin-centered GLB."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import bpy


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from common import (  # noqa: E402
    REPOSITORY_ROOT,
    deep_merge,
    display_path,
    load_json,
    require_build_path,
    resolve_from_repository,
    write_json_atomic,
)
from manifest import write_release_manifest  # noqa: E402
from validate_assets import DEFAULT_CONFIG, validate_scene  # noqa: E402


def blender_script_arguments() -> Sequence[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export validated building assets to GLB")
    parser.add_argument(
        "--config",
        default="automation/config/release_config.json",
        help="Config path; relative paths are resolved from the repository root",
    )
    parser.add_argument(
        "--output-dir",
        default="build/release/GLB",
        help="GLB root; it must resolve inside the repository build directory",
    )
    parser.add_argument(
        "--validation-report",
        default="build/validation_report.json",
        help="Fresh pre-export validation report path",
    )
    parser.add_argument(
        "--report",
        default="build/export_report.json",
        help="Machine-readable export report path",
    )
    parser.add_argument(
        "--manifest-dir",
        default="build/release/Manifest",
        help="JSON/CSV manifest directory; it must be inside build",
    )
    parser.add_argument(
        "--asset",
        action="append",
        default=[],
        help="Export only this asset ID; may be supplied more than once",
    )
    return parser.parse_args(argv)


def collect_assets(config: Dict[str, Any]) -> List[Tuple[str, Any]]:
    assets: List[Tuple[str, Any]] = []
    for category in config["collections"]:
        collection = bpy.data.collections.get(category)
        if collection is None:
            continue
        for obj in sorted(collection.all_objects, key=lambda item: item.name):
            if obj.type == "MESH":
                assets.append((category, obj))
    return assets


def select_only(obj: Any) -> None:
    for candidate in bpy.context.view_layer.objects:
        candidate.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def export_one_asset(obj: Any, final_path: Path) -> int:
    """Export through a temporary file, replacing the destination only on success."""
    final_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{obj.name}.", suffix=".glb", dir=str(final_path.parent)
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    original_world_matrix = obj.matrix_world.copy()

    try:
        origin_matrix = original_world_matrix.copy()
        origin_matrix.translation = (0.0, 0.0, 0.0)
        obj.matrix_world = origin_matrix
        bpy.context.view_layer.update()
        if obj.matrix_world.translation.length > 0.000001:
            raise RuntimeError(f"Could not move {obj.name} to world origin for export")

        select_only(obj)
        result = bpy.ops.export_scene.gltf(
            filepath=str(temporary_path),
            check_existing=False,
            export_format="GLB",
            use_selection=True,
            use_visible=False,
            use_renderable=False,
            export_cameras=False,
            export_lights=False,
            export_texcoords=True,
            export_normals=True,
            # glTF tangents are optional. Consumers reconstruct them when needed;
            # requesting them here fails on some finished, non-triangulated meshes.
            export_tangents=False,
            export_materials="EXPORT",
            export_animations=False,
            export_skins=False,
            export_morph=False,
            export_yup=True,
            export_apply=False,
            export_image_format="AUTO",
            export_keep_originals=False,
            export_unused_images=False,
            export_unused_textures=False,
            will_save_settings=False,
        )
        if "FINISHED" not in result:
            raise RuntimeError(f"Blender glTF exporter returned {sorted(result)}")
        size_bytes = temporary_path.stat().st_size
        if size_bytes <= 0:
            raise RuntimeError("Blender produced an empty GLB")
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, final_path)
        return size_bytes
    finally:
        obj.matrix_world = original_world_matrix
        bpy.context.view_layer.update()
        if temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    arguments = parse_arguments(blender_script_arguments())
    if bpy.context.mode != "OBJECT":
        raise RuntimeError(f"Exporter requires Object Mode, found {bpy.context.mode}")

    config_path = resolve_from_repository(arguments.config)
    output_directory = resolve_from_repository(arguments.output_dir)
    validation_report_path = resolve_from_repository(arguments.validation_report)
    export_report_path = resolve_from_repository(arguments.report)
    manifest_directory = resolve_from_repository(arguments.manifest_dir)
    require_build_path(output_directory, "Output directory")
    require_build_path(validation_report_path, "Validation report")
    require_build_path(export_report_path, "Export report")
    require_build_path(manifest_directory, "Manifest directory")

    config = deep_merge(DEFAULT_CONFIG, load_json(config_path))
    validation_report = validate_scene(config)
    write_json_atomic(validation_report_path, validation_report)
    if validation_report["status"] == "error":
        summary = validation_report["summary"]
        print(
            f"Export blocked: validation found {summary['error_count']} errors "
            f"across {summary['error_asset_count']} assets"
        )
        return 1

    assets = collect_assets(config)
    requested_assets = set(arguments.asset)
    known_asset_names = {obj.name for _, obj in assets}
    unknown_assets = sorted(requested_assets - known_asset_names)
    if unknown_assets:
        raise ValueError(f"Unknown --asset value(s): {', '.join(unknown_assets)}")
    if requested_assets:
        assets = [(category, obj) for category, obj in assets if obj.name in requested_assets]

    original_active = bpy.context.view_layer.objects.active
    original_selection = {
        obj: obj.select_get() for obj in bpy.context.view_layer.objects
    }
    exported: Dict[str, Dict[str, Any]] = {}
    failures: Dict[str, Dict[str, str]] = {}

    try:
        for category, obj in assets:
            final_path = output_directory / category / f"{obj.name}.glb"
            try:
                size_bytes = export_one_asset(obj, final_path)
                exported[obj.name] = {
                    "category": category,
                    "path": display_path(final_path),
                    "size_bytes": size_bytes,
                }
                print(f"Exported {obj.name}: {display_path(final_path)}")
            except Exception as error:
                failures[obj.name] = {
                    "category": category,
                    "error": f"{type(error).__name__}: {error}",
                }
                print(f"Failed {obj.name}: {type(error).__name__}: {error}")
    finally:
        for obj, was_selected in original_selection.items():
            obj.select_set(was_selected)
        bpy.context.view_layer.objects.active = original_active
        bpy.context.view_layer.update()

    if failures:
        manifest_result: Dict[str, Any] = {
            "status": "skipped",
            "reason": "One or more asset exports failed",
        }
    elif requested_assets:
        manifest_result = {
            "status": "skipped",
            "reason": "Partial --asset exports do not replace the full release manifest",
        }
    else:
        try:
            manifest_result = write_release_manifest(
                manifest_directory, validation_report, exported, config
            )
        except Exception as error:
            manifest_result = {
                "status": "error",
                "error": f"{type(error).__name__}: {error}",
            }

    pipeline_failed = bool(failures) or manifest_result["status"] == "error"
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "error" if pipeline_failed else "pass",
        "source_blend": display_path(Path(bpy.data.filepath)),
        "blender_version": bpy.app.version_string,
        "output_directory": display_path(output_directory),
        "validation_status": validation_report["status"],
        "summary": {
            "requested_asset_count": len(assets),
            "exported_asset_count": len(exported),
            "failed_asset_count": len(failures),
        },
        "assets": exported,
        "failures": failures,
        "manifest": manifest_result,
    }
    write_json_atomic(export_report_path, report)
    print(
        f"Export {report['status'].upper()}: {len(exported)} exported, "
        f"{len(failures)} failed"
    )
    print(f"Export report: {display_path(export_report_path)}")
    return 1 if pipeline_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
