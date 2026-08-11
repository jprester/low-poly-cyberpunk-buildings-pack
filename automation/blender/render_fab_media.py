"""Render Fab-compliant marketplace gallery images from the source assets."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

import bpy
from mathutils import Vector


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from common import (  # noqa: E402
    deep_merge,
    display_path,
    load_json,
    require_build_path,
    resolve_from_repository,
    write_json_atomic,
)
from render_collection_overviews import layout_assets  # noqa: E402
from render_previews import PreviewStudio  # noqa: E402
from validate_assets import DEFAULT_CONFIG, validate_scene  # noqa: E402


def blender_script_arguments() -> Sequence[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Fab marketplace media")
    parser.add_argument(
        "--config",
        default="automation/config/release_config.json",
        help="Config path; relative paths are resolved from the repository root",
    )
    parser.add_argument(
        "--output-dir",
        default="build/fab_media",
        help="Fab media output directory; it must be inside build",
    )
    parser.add_argument(
        "--validation-report",
        default="build/validation_report.json",
        help="Fresh pre-render validation report path",
    )
    parser.add_argument(
        "--report",
        default="build/fab_media_report.json",
        help="Machine-readable Fab media report path",
    )
    return parser.parse_args(argv)


def collect_assets(config: Dict[str, Any]) -> Dict[str, List[Any]]:
    result: Dict[str, List[Any]] = {}
    for category in config["collections"]:
        collection = bpy.data.collections.get(category)
        if collection is None:
            result[category] = []
            continue
        result[category] = sorted(
            (obj for obj in collection.all_objects if obj.type == "MESH"),
            key=lambda item: item.name,
        )
    return result


def render_layout(
    studio: PreviewStudio,
    sources: List[Any],
    depsgraph: Any,
    spacing_factor: float,
    output_path: Path,
) -> Dict[str, Any]:
    preview_objects: List[Any] = []
    try:
        preview_objects, corners, layout = layout_assets(
            studio, sources, depsgraph, spacing_factor
        )
        if not corners:
            raise ValueError("Cannot render an empty Fab media layout")
        size = Vector(tuple(layout["layout_dimensions_m"]))
        camera_distance = studio.frame_asset(corners, size)
        result = studio.render_to_path(output_path, output_path.stem)
        result.update(
            {
                "asset_count": len(sources),
                "asset_ids": [source.name for source in sources],
                "camera_distance_m": round(camera_distance, 6),
                "layout": layout,
            }
        )
        return result
    finally:
        for preview in preview_objects:
            if preview.name in bpy.data.objects:
                bpy.data.objects.remove(preview, do_unlink=True)


def main() -> int:
    arguments = parse_arguments(blender_script_arguments())
    if bpy.context.mode != "OBJECT":
        raise RuntimeError(f"Fab media renderer requires Object Mode, found {bpy.context.mode}")

    config_path = resolve_from_repository(arguments.config)
    output_directory = resolve_from_repository(arguments.output_dir)
    validation_report_path = resolve_from_repository(arguments.validation_report)
    report_path = resolve_from_repository(arguments.report)
    require_build_path(output_directory, "Fab media output directory")
    require_build_path(validation_report_path, "Validation report")
    require_build_path(report_path, "Fab media report")

    config = deep_merge(DEFAULT_CONFIG, load_json(config_path))
    settings = deep_merge(config["preview"], config["fab_media"])
    expected_resolution = [1920, 1080]
    if list(settings["resolution"]) != expected_resolution:
        raise ValueError(f"Fab media resolution must be {expected_resolution}")

    validation_report = validate_scene(config)
    write_json_atomic(validation_report_path, validation_report)
    if validation_report["status"] == "error":
        print(
            "Fab media rendering blocked by "
            f"{validation_report['summary']['error_count']} validation errors"
        )
        return 1

    assets_by_category = collect_assets(config)
    all_assets = [
        asset
        for category in config["collections"]
        for asset in assets_by_category[category]
    ]
    assets_by_name = {asset.name: asset for asset in all_assets}
    hero_names = list(settings["hero_assets"])
    unknown_hero_assets = sorted(set(hero_names) - set(assets_by_name))
    if unknown_hero_assets:
        raise ValueError(
            f"Unknown fab_media.hero_assets: {', '.join(unknown_hero_assets)}"
        )

    layouts = [
        ("01_hero.jpg", [assets_by_name[name] for name in hero_names]),
        ("02_full_collection.jpg", all_assets),
        ("03_residential_collection.jpg", assets_by_category["Residential"]),
        ("04_commercial_collection.jpg", assets_by_category["Commercial"]),
        ("05_skyscraper_collection.jpg", assets_by_category["Skyscraper"]),
    ]

    output_directory.mkdir(parents=True, exist_ok=True)
    rendered: Dict[str, Dict[str, Any]] = {}
    failures: Dict[str, Dict[str, str]] = {}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    studio = PreviewStudio(settings)
    try:
        for filename, sources in layouts:
            output_path = output_directory / filename
            try:
                result = render_layout(
                    studio,
                    sources,
                    depsgraph,
                    float(settings["spacing_factor"]),
                    output_path,
                )
                rendered[filename] = result
                print(f"Rendered Fab media: {display_path(output_path)}")
            except Exception as error:
                failures[filename] = {
                    "error": f"{type(error).__name__}: {error}"
                }
                print(f"Failed {filename}: {type(error).__name__}: {error}")
    finally:
        studio.close()

    maximum_file_size = int(settings["maximum_file_size_bytes"])
    maximum_total_size = int(settings["maximum_total_size_bytes"])
    oversized = {
        name: details["size_bytes"]
        for name, details in rendered.items()
        if int(details["size_bytes"]) >= maximum_file_size
    }
    total_size = sum(int(details["size_bytes"]) for details in rendered.values())
    if oversized:
        failures["file_size"] = {
            "error": f"Images must each be smaller than {maximum_file_size} bytes",
            "files": oversized,
        }
    if total_size >= maximum_total_size:
        failures["total_size"] = {
            "error": f"Gallery images must total less than {maximum_total_size} bytes",
            "actual_size_bytes": total_size,
        }

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "error" if failures else "pass",
        "source_blend": display_path(Path(bpy.data.filepath)),
        "blender_version": bpy.app.version_string,
        "output_directory": display_path(output_directory),
        "validation_status": validation_report["status"],
        "constraints": {
            "resolution_px": expected_resolution,
            "maximum_file_size_bytes_exclusive": maximum_file_size,
            "maximum_total_size_bytes_exclusive": maximum_total_size,
            "format": "JPEG",
        },
        "summary": {
            "requested_image_count": len(layouts),
            "rendered_image_count": len(rendered),
            "failed_check_count": len(failures),
            "total_size_bytes": total_size,
        },
        "images": rendered,
        "failures": failures,
    }
    write_json_atomic(report_path, report)
    print(
        f"Fab media {report['status'].upper()}: {len(rendered)} rendered, "
        f"{len(failures)} failed checks"
    )
    print(f"Fab media report: {display_path(report_path)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
