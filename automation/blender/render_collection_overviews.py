"""Render automatically arranged overview images for each asset category."""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import bpy
from mathutils import Matrix, Vector


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
from render_previews import PreviewStudio, evaluated_local_bounds  # noqa: E402
from validate_assets import DEFAULT_CONFIG, validate_scene  # noqa: E402


def blender_script_arguments() -> Sequence[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render category collection overviews")
    parser.add_argument(
        "--config",
        default="automation/config/release_config.json",
        help="Config path; relative paths are resolved from the repository root",
    )
    parser.add_argument(
        "--output-dir",
        default="build/release/Preview",
        help="Overview output directory; it must be inside build",
    )
    parser.add_argument(
        "--validation-report",
        default="build/validation_report.json",
        help="Fresh pre-render validation report path",
    )
    parser.add_argument(
        "--report",
        default="build/overview_report.json",
        help="Machine-readable overview report path",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Render only this configured category; may be supplied more than once",
    )
    return parser.parse_args(argv)


def category_assets(category: str) -> List[Any]:
    collection = bpy.data.collections.get(category)
    if collection is None:
        return []
    return sorted(
        (obj for obj in collection.all_objects if obj.type == "MESH"),
        key=lambda item: item.name,
    )


def layout_assets(
    studio: PreviewStudio,
    sources: List[Any],
    depsgraph: Any,
    spacing_factor: float,
) -> Tuple[List[Any], List[Vector], Dict[str, Any]]:
    bounds = []
    maximum_width = 0.0
    maximum_depth = 0.0
    for source in sources:
        corners, size = evaluated_local_bounds(source, depsgraph)
        bounds.append((source, corners, size))
        maximum_width = max(maximum_width, size.x)
        maximum_depth = max(maximum_depth, size.y)

    columns = int(math.ceil(math.sqrt(len(sources))))
    rows = int(math.ceil(len(sources) / columns))
    cell_width = maximum_width * spacing_factor
    cell_depth = maximum_depth * spacing_factor
    preview_objects: List[Any] = []
    combined_corners: List[Vector] = []
    index = 0

    for row in range(rows):
        row_items = bounds[index : index + columns]
        row_y = ((rows - 1) / 2.0 - row) * cell_depth
        for column, (source, corners, _size) in enumerate(row_items):
            column_x = (column - (len(row_items) - 1) / 2.0) * cell_width
            ground_z = min(corner.z for corner in corners)
            offset = Vector((column_x, row_y, -ground_z))
            preview = source.copy()
            preview.name = f"__RELEASE_OVERVIEW__{source.name}"
            preview.parent = None
            preview.matrix_world = Matrix.Translation(offset)
            preview.hide_render = False
            studio.scene.collection.objects.link(preview)
            preview_objects.append(preview)
            combined_corners.extend(corner + offset for corner in corners)
        index += len(row_items)

    minimum = Vector(
        tuple(min(corner[axis] for corner in combined_corners) for axis in range(3))
    )
    maximum = Vector(
        tuple(max(corner[axis] for corner in combined_corners) for axis in range(3))
    )
    layout = {
        "columns": columns,
        "rows": rows,
        "cell_size_m": [round(cell_width, 6), round(cell_depth, 6)],
        "layout_dimensions_m": [round(float(value), 6) for value in maximum - minimum],
    }
    return preview_objects, combined_corners, layout


def main() -> int:
    arguments = parse_arguments(blender_script_arguments())
    if bpy.context.mode != "OBJECT":
        raise RuntimeError(f"Overview renderer requires Object Mode, found {bpy.context.mode}")

    config_path = resolve_from_repository(arguments.config)
    output_directory = resolve_from_repository(arguments.output_dir)
    validation_report_path = resolve_from_repository(arguments.validation_report)
    overview_report_path = resolve_from_repository(arguments.report)
    require_build_path(output_directory, "Overview output directory")
    require_build_path(validation_report_path, "Validation report")
    require_build_path(overview_report_path, "Overview report")

    config = deep_merge(DEFAULT_CONFIG, load_json(config_path))
    validation_report = validate_scene(config)
    write_json_atomic(validation_report_path, validation_report)
    if validation_report["status"] == "error":
        print(f"Overview rendering blocked by {validation_report['summary']['error_count']} validation errors")
        return 1

    categories = list(config["collections"])
    requested_categories = set(arguments.category)
    unknown_categories = sorted(requested_categories - set(categories))
    if unknown_categories:
        raise ValueError(f"Unknown --category value(s): {', '.join(unknown_categories)}")
    if requested_categories:
        categories = [category for category in categories if category in requested_categories]

    studio_settings = deep_merge(config["preview"], config["collection_overview"])
    studio = PreviewStudio(studio_settings)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    rendered: Dict[str, Dict[str, Any]] = {}
    failures: Dict[str, Dict[str, str]] = {}
    try:
        for category in categories:
            sources = category_assets(category)
            preview_objects: List[Any] = []
            try:
                preview_objects, corners, layout = layout_assets(
                    studio,
                    sources,
                    depsgraph,
                    float(studio_settings["spacing_factor"]),
                )
                layout_size = Vector(tuple(layout["layout_dimensions_m"]))
                camera_distance = studio.frame_asset(corners, layout_size)
                output_path = output_directory / f"{category.lower()}_collection.png"
                result = studio.render_to_path(output_path, f"{category.lower()}_collection")
                result.update(
                    {
                        "asset_count": len(sources),
                        "asset_ids": [source.name for source in sources],
                        "camera_distance_m": round(camera_distance, 6),
                        "layout": layout,
                    }
                )
                rendered[category] = result
                print(f"Rendered {category}: {display_path(output_path)}")
            except Exception as error:
                failures[category] = {"error": f"{type(error).__name__}: {error}"}
                print(f"Failed {category}: {type(error).__name__}: {error}")
            finally:
                for preview in preview_objects:
                    if preview.name in bpy.data.objects:
                        bpy.data.objects.remove(preview, do_unlink=True)
    finally:
        studio.close()

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "error" if failures else "pass",
        "source_blend": display_path(Path(bpy.data.filepath)),
        "blender_version": bpy.app.version_string,
        "output_directory": display_path(output_directory),
        "validation_status": validation_report["status"],
        "summary": {
            "requested_category_count": len(categories),
            "rendered_category_count": len(rendered),
            "failed_category_count": len(failures),
        },
        "categories": rendered,
        "failures": failures,
    }
    write_json_atomic(overview_report_path, report)
    print(
        f"Overview {report['status'].upper()}: {len(rendered)} rendered, "
        f"{len(failures)} failed"
    )
    print(f"Overview report: {display_path(overview_report_path)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
