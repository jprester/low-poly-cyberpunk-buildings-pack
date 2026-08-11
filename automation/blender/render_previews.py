"""Render standardized per-asset previews in a temporary Blender scene."""

from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import bpy
from bpy_extras.object_utils import world_to_camera_view
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
from validate_assets import DEFAULT_CONFIG, validate_scene  # noqa: E402


TEMPORARY_PREFIX = "__RELEASE_PREVIEW__"


def blender_script_arguments() -> Sequence[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render standardized building previews")
    parser.add_argument(
        "--config",
        default="automation/config/release_config.json",
        help="Config path; relative paths are resolved from the repository root",
    )
    parser.add_argument(
        "--output-dir",
        default="build/release/Preview",
        help="Preview root; it must resolve inside the repository build directory",
    )
    parser.add_argument(
        "--validation-report",
        default="build/validation_report.json",
        help="Fresh pre-render validation report path",
    )
    parser.add_argument(
        "--report",
        default="build/preview_report.json",
        help="Machine-readable preview report path",
    )
    parser.add_argument(
        "--asset",
        action="append",
        default=[],
        help="Render only this asset ID; may be supplied more than once",
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


def evaluated_local_bounds(obj: Any, depsgraph: Any) -> Tuple[List[Vector], Vector]:
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        if not mesh.vertices:
            raise ValueError(f"Cannot frame empty mesh {obj.name}")
        minimum = Vector(
            tuple(min(vertex.co[axis] for vertex in mesh.vertices) for axis in range(3))
        )
        maximum = Vector(
            tuple(max(vertex.co[axis] for vertex in mesh.vertices) for axis in range(3))
        )
    finally:
        evaluated.to_mesh_clear()
    corners = [
        Vector((x, y, z))
        for x in (minimum.x, maximum.x)
        for y in (minimum.y, maximum.y)
        for z in (minimum.z, maximum.z)
    ]
    return corners, maximum - minimum


def point_at(obj: Any, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_sun(scene: Any, name: str, direction: Vector, energy: float, color: Tuple[float, float, float]) -> Tuple[Any, Any]:
    data = bpy.data.lights.new(f"{TEMPORARY_PREFIX}{name}_Data", type="SUN")
    data.energy = energy
    data.angle = math.radians(18.0)
    data.color = color
    obj = bpy.data.objects.new(f"{TEMPORARY_PREFIX}{name}", data)
    obj.location = direction
    point_at(obj, Vector((0.0, 0.0, 0.0)))
    scene.collection.objects.link(obj)
    return obj, data


class PreviewStudio:
    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings
        self.scene = bpy.data.scenes.new(f"{TEMPORARY_PREFIX}Scene")
        self.objects: List[Any] = []
        self.object_data: List[Any] = []
        self.materials: List[Any] = []
        self.world = bpy.data.worlds.new(f"{TEMPORARY_PREFIX}World")
        self.scene.world = self.world
        self.world.color = tuple(settings["background_color"])
        if self.world.node_tree is not None:
            background = self.world.node_tree.nodes.get("Background")
            if background is not None:
                color = tuple(settings["background_color"]) + (1.0,)
                background.inputs["Color"].default_value = color
                background.inputs["Strength"].default_value = 0.22

        self.scene.render.engine = "BLENDER_EEVEE"
        self.scene.render.resolution_x = int(settings["resolution"][0])
        self.scene.render.resolution_y = int(settings["resolution"][1])
        self.scene.render.resolution_percentage = 100
        self.scene.render.image_settings.file_format = "PNG"
        self.scene.render.image_settings.color_mode = "RGB"
        self.scene.render.image_settings.color_depth = "8"
        self.scene.render.film_transparent = False
        self.scene.render.use_file_extension = True
        self.scene.view_settings.view_transform = "AgX"
        self.scene.view_settings.look = "None"

        camera_data = bpy.data.cameras.new(f"{TEMPORARY_PREFIX}Camera_Data")
        camera_data.lens = float(settings["lens_mm"])
        camera_data.clip_start = 0.05
        self.camera = bpy.data.objects.new(f"{TEMPORARY_PREFIX}Camera", camera_data)
        self.scene.collection.objects.link(self.camera)
        self.scene.camera = self.camera
        self.objects.append(self.camera)
        self.object_data.append(camera_data)

        ground_mesh = bpy.data.meshes.new(f"{TEMPORARY_PREFIX}Ground_Mesh")
        ground_mesh.from_pydata(
            [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)],
            [],
            [(0, 1, 2, 3)],
        )
        ground_mesh.update()
        self.ground = bpy.data.objects.new(f"{TEMPORARY_PREFIX}Ground", ground_mesh)
        ground_material = bpy.data.materials.new(f"{TEMPORARY_PREFIX}Ground_Material")
        ground_material.diffuse_color = tuple(settings["ground_color"])
        ground_material.roughness = 0.82
        if ground_material.node_tree is not None:
            principled = ground_material.node_tree.nodes.get("Principled BSDF")
            if principled is not None:
                principled.inputs["Base Color"].default_value = tuple(settings["ground_color"])
                principled.inputs["Roughness"].default_value = 0.82
        self.ground.data.materials.append(ground_material)
        self.scene.collection.objects.link(self.ground)
        self.objects.append(self.ground)
        self.object_data.append(ground_mesh)
        self.materials.append(ground_material)

        for light in (
            add_sun(self.scene, "Key", Vector((4.0, -6.0, 8.0)), 3.0, (1.0, 0.82, 0.68)),
            add_sun(self.scene, "Fill", Vector((-5.0, -2.0, 4.0)), 0.8, (0.48, 0.65, 1.0)),
            add_sun(self.scene, "Rim", Vector((1.0, 6.0, 5.0)), 1.1, (0.7, 0.45, 1.0)),
        ):
            self.objects.append(light[0])
            self.object_data.append(light[1])

    def frame_asset(self, corners: List[Vector], size: Vector) -> float:
        target = sum(corners, Vector((0.0, 0.0, 0.0))) / len(corners)
        view_direction = Vector(tuple(self.settings["view_direction"])).normalized()
        rotation = (-view_direction).to_track_quat("-Z", "Y")
        padding = float(self.settings["frame_padding"])
        self.camera.rotation_mode = "QUATERNION"
        self.camera.rotation_quaternion = rotation
        margin = (1.0 - 1.0 / padding) / 2.0

        def fits(distance: float) -> bool:
            self.camera.location = target + view_direction * distance
            self.scene.view_layers[0].update()
            projected = [world_to_camera_view(self.scene, self.camera, corner) for corner in corners]
            return all(
                point.z > self.camera.data.clip_start
                and margin <= point.x <= 1.0 - margin
                and margin <= point.y <= 1.0 - margin
                for point in projected
            )

        lower = max(max(size) * 0.01, 0.1)
        upper = max(max(size), 1.0)
        while not fits(upper):
            upper *= 2.0
        for _ in range(40):
            middle = (lower + upper) / 2.0
            if fits(middle):
                upper = middle
            else:
                lower = middle
        distance = upper
        self.camera.location = target + view_direction * distance
        self.scene.view_layers[0].update()
        self.camera.data.clip_end = distance + max(size) * 8.0

        ground_radius = max(size.x, size.y) * float(
            self.settings.get("ground_scale_factor", 2.5)
        )
        self.ground.scale = (ground_radius, ground_radius, 1.0)
        self.ground.location = (
            target.x,
            target.y,
            min(corner.z for corner in corners) - 0.02,
        )
        return distance

    def render_to_path(self, output_path: Path, label: str) -> Dict[str, Any]:
        """Atomically render the current temporary studio scene to PNG or JPEG."""
        suffix = output_path.suffix.lower()
        if suffix == ".png":
            file_format = "PNG"
        elif suffix in {".jpg", ".jpeg"}:
            file_format = "JPEG"
        else:
            raise ValueError(f"Unsupported preview image extension: {output_path.suffix}")

        self.scene.render.image_settings.file_format = file_format
        if file_format == "JPEG":
            self.scene.render.image_settings.quality = int(
                self.settings.get("jpeg_quality", 90)
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{label}.", suffix=suffix, dir=str(output_path.parent)
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            self.scene.render.filepath = str(temporary_path)
            result = bpy.ops.render.render(write_still=True, scene=self.scene.name)
            if "FINISHED" not in result:
                raise RuntimeError(f"Blender render returned {sorted(result)}")
            size_bytes = temporary_path.stat().st_size
            if size_bytes <= 0:
                raise RuntimeError("Blender produced an empty preview image")
            os.chmod(temporary_path, 0o644)
            os.replace(temporary_path, output_path)
            return {
                "path": display_path(output_path),
                "size_bytes": size_bytes,
                "resolution_px": [self.scene.render.resolution_x, self.scene.render.resolution_y],
            }
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def render_asset(self, source_obj: Any, output_path: Path, depsgraph: Any) -> Dict[str, Any]:
        preview_obj = source_obj.copy()
        preview_obj.name = f"{TEMPORARY_PREFIX}{source_obj.name}"
        preview_obj.parent = None
        preview_obj.matrix_world = Matrix.Identity(4)
        preview_obj.hide_render = False
        self.scene.collection.objects.link(preview_obj)
        corners, size = evaluated_local_bounds(source_obj, depsgraph)
        camera_distance = self.frame_asset(corners, size)
        try:
            result = self.render_to_path(output_path, source_obj.name)
            result["camera_distance_m"] = round(camera_distance, 6)
            result["asset_dimensions_m"] = [round(float(value), 6) for value in size]
            return result
        finally:
            bpy.data.objects.remove(preview_obj, do_unlink=True)

    def close(self) -> None:
        bpy.data.scenes.remove(self.scene)
        for obj in self.objects:
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for data in self.object_data:
            collection = {
                "CAMERA": bpy.data.cameras,
                "LIGHT": bpy.data.lights,
                "MESH": bpy.data.meshes,
            }.get(data.bl_rna.identifier.upper())
            if collection is not None and data.name in collection:
                collection.remove(data)
        for material in self.materials:
            if material.name in bpy.data.materials:
                bpy.data.materials.remove(material)
        if self.world.name in bpy.data.worlds:
            bpy.data.worlds.remove(self.world)


def main() -> int:
    arguments = parse_arguments(blender_script_arguments())
    if bpy.context.mode != "OBJECT":
        raise RuntimeError(f"Preview renderer requires Object Mode, found {bpy.context.mode}")

    config_path = resolve_from_repository(arguments.config)
    output_directory = resolve_from_repository(arguments.output_dir)
    validation_report_path = resolve_from_repository(arguments.validation_report)
    preview_report_path = resolve_from_repository(arguments.report)
    require_build_path(output_directory, "Preview output directory")
    require_build_path(validation_report_path, "Validation report")
    require_build_path(preview_report_path, "Preview report")

    config = deep_merge(DEFAULT_CONFIG, load_json(config_path))
    validation_report = validate_scene(config)
    write_json_atomic(validation_report_path, validation_report)
    if validation_report["status"] == "error":
        print(f"Preview rendering blocked by {validation_report['summary']['error_count']} validation errors")
        return 1

    assets = collect_assets(config)
    requested_assets = set(arguments.asset)
    known_asset_names = {obj.name for _, obj in assets}
    unknown_assets = sorted(requested_assets - known_asset_names)
    if unknown_assets:
        raise ValueError(f"Unknown --asset value(s): {', '.join(unknown_assets)}")
    if requested_assets:
        assets = [(category, obj) for category, obj in assets if obj.name in requested_assets]

    depsgraph = bpy.context.evaluated_depsgraph_get()
    rendered: Dict[str, Dict[str, Any]] = {}
    failures: Dict[str, Dict[str, str]] = {}
    studio = PreviewStudio(config["preview"])
    try:
        for category, obj in assets:
            output_path = output_directory / category / f"{obj.name}_preview.png"
            try:
                result = studio.render_asset(obj, output_path, depsgraph)
                result["category"] = category
                rendered[obj.name] = result
                print(f"Rendered {obj.name}: {display_path(output_path)}")
            except Exception as error:
                failures[obj.name] = {
                    "category": category,
                    "error": f"{type(error).__name__}: {error}",
                }
                print(f"Failed {obj.name}: {type(error).__name__}: {error}")
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
            "requested_asset_count": len(assets),
            "rendered_asset_count": len(rendered),
            "failed_asset_count": len(failures),
        },
        "assets": rendered,
        "failures": failures,
    }
    write_json_atomic(preview_report_path, report)
    print(
        f"Preview {report['status'].upper()}: {len(rendered)} rendered, "
        f"{len(failures)} failed"
    )
    print(f"Preview report: {display_path(preview_report_path)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
