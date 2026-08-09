"""Read-only validation for the cyberpunk building catalogue.

Run through Blender, not a standalone Python interpreter. The only filesystem
mutation is an atomic JSON report write. This script never saves the .blend.
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import bpy

# Blender's --python runner does not add this file's directory to sys.path.
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from common import (
    REPOSITORY_ROOT,
    deep_merge,
    display_path,
    load_json,
    resolve_from_repository,
    write_json_atomic,
)


DEFAULT_CONFIG: Dict[str, Any] = {
    "schema_version": 1,
    "collections": {
        "Residential": "RES",
        "Commercial": "COM",
        "Skyscraper": "SKY",
    },
    "material_requirements": {},
    "thresholds": {
        "transform_epsilon": 0.0001,
        "origin_ground_warning_m": 0.01,
        "origin_ground_error_m": 0.1,
        "origin_center_warning_m": 0.1,
        "origin_center_warning_ratio": 0.01,
        "triangle_warning": 10000,
        "material_slot_warning": 4,
        "texture_dimension_warning": 4096,
    },
}

ROLE_INPUT_NAMES = {
    "base_color": ("Base Color",),
    "roughness": ("Roughness",),
    "emission": ("Emission Color", "Emission"),
    "normal": ("Normal",),
}


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate release assets in the open .blend")
    parser.add_argument(
        "--output",
        default="build/validation_report.json",
        help="Report path; relative paths are resolved from the repository root",
    )
    parser.add_argument(
        "--config",
        default="automation/config/release_config.json",
        help="Config path; relative paths are resolved from the repository root",
    )
    parser.add_argument(
        "--fail-on-errors",
        action="store_true",
        help="Exit Blender with status 1 after writing a report containing errors",
    )
    return parser.parse_args(argv)


def blender_script_arguments() -> Sequence[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def issue(code: str, message: str, **details: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {"code": code, "message": message}
    if details:
        result["details"] = details
    return result


def rounded_vector(values: Iterable[float]) -> List[float]:
    return [round(float(value), 6) for value in values]


def status_for(errors: Sequence[Any], warnings: Sequence[Any]) -> str:
    if errors:
        return "error"
    if warnings:
        return "warning"
    return "pass"


def canonical_material_name(name: str, requirements: Dict[str, Any]) -> Optional[str]:
    if name in requirements:
        return name
    match = re.match(r"^(.*)\.\d{3}$", name)
    if match and match.group(1) in requirements:
        return match.group(1)
    return None


def find_input(node: Any, names: Sequence[str]) -> Optional[Any]:
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    return None


def upstream_nodes(socket: Any) -> Set[Any]:
    found: Set[Any] = set()
    pending = [link.from_node for link in socket.links]
    while pending:
        node = pending.pop()
        if node in found:
            continue
        found.add(node)
        for node_input in node.inputs:
            pending.extend(link.from_node for link in node_input.links)
    return found


def image_path_exists(image: Any) -> bool:
    if getattr(image, "packed_file", None):
        return True
    if getattr(image, "packed_files", None):
        return True
    if image.source == "GENERATED":
        return True
    if not image.filepath:
        return False
    resolved = bpy.path.abspath(image.filepath, library=image.library)
    if "<UDIM>" in resolved:
        return bool(glob.glob(resolved.replace("<UDIM>", "*")))
    return os.path.isfile(resolved)


def image_display_path(image: Any) -> str:
    if not image.filepath:
        return ""
    if image.filepath.startswith("//"):
        return image.filepath
    resolved = Path(bpy.path.abspath(image.filepath, library=image.library))
    return display_path(resolved)


def material_is_double_sided(material: Any) -> bool:
    if hasattr(material, "use_backface_culling"):
        return not bool(material.use_backface_culling)
    return False


def inspect_material(
    material: Any,
    requirements: Dict[str, Any],
    texture_dimension_warning: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Set[Any]]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    textures: List[Dict[str, Any]] = []
    used_images: Set[Any] = set()

    if material is None:
        errors.append(issue("empty_material_slot", "A material slot has no material assigned"))
        return errors, warnings, textures, used_images
    if material.node_tree is None:
        warnings.append(
            issue(
                "material_without_nodes",
                f"Material {material.name} does not use a node tree",
                material=material.name,
            )
        )
        return errors, warnings, textures, used_images

    canonical_name = canonical_material_name(material.name, requirements)
    required_roles = requirements.get(canonical_name, []) if canonical_name else []
    principled_nodes = [
        node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
    ]
    role_images: Dict[str, Set[Any]] = {role: set() for role in ROLE_INPUT_NAMES}

    for principled in principled_nodes:
        for role, input_names in ROLE_INPUT_NAMES.items():
            socket = find_input(principled, input_names)
            if socket is None or not socket.is_linked:
                continue
            nodes = upstream_nodes(socket)
            images = {
                node.image
                for node in nodes
                if node.type == "TEX_IMAGE" and node.image is not None
            }
            role_images[role].update(images)
            if role == "normal" and images and not any(
                node.type == "NORMAL_MAP" for node in nodes
            ):
                errors.append(
                    issue(
                        "normal_map_node_missing",
                        f"Material {material.name} feeds normal texture data to Principled Normal without a Normal Map node",
                        material=material.name,
                    )
                )

    for role in required_roles:
        if not role_images.get(role):
            errors.append(
                issue(
                    "required_texture_missing",
                    f"Material {material.name} has no image texture connected for required role {role}",
                    material=material.name,
                    role=role,
                )
            )

    texture_roles: Dict[Any, Set[str]] = {}
    for role, images in role_images.items():
        for image in images:
            texture_roles.setdefault(image, set()).add(role)

    linked_image_nodes = [
        node
        for node in material.node_tree.nodes
        if node.type == "TEX_IMAGE" and any(output.is_linked for output in node.outputs)
    ]
    for node in linked_image_nodes:
        if node.image is None:
            errors.append(
                issue(
                    "image_node_without_image",
                    f"Material {material.name} contains a linked Image Texture node with no image",
                    material=material.name,
                    node=node.name,
                )
            )
            continue
        used_images.add(node.image)
        texture_roles.setdefault(node.image, set())

    for image in sorted(used_images, key=lambda item: item.name):
        roles = sorted(texture_roles.get(image, set()))
        width, height = (int(image.size[0]), int(image.size[1]))
        path_exists = image_path_exists(image)
        texture = {
            "name": image.name,
            "path": image_display_path(image),
            "roles": roles,
            "size_px": [width, height],
            "colorspace": image.colorspace_settings.name,
            "packed": bool(getattr(image, "packed_file", None)),
            "path_exists": path_exists,
        }
        textures.append(texture)

        if not path_exists:
            errors.append(
                issue(
                    "broken_image_reference",
                    f"Image {image.name} used by {material.name} cannot be found",
                    material=material.name,
                    image=image.name,
                    path=texture["path"],
                )
            )
        if max(width, height) > texture_dimension_warning:
            warnings.append(
                issue(
                    "large_texture",
                    f"Image {image.name} exceeds the configured texture dimension warning",
                    image=image.name,
                    size_px=[width, height],
                    threshold_px=texture_dimension_warning,
                )
            )

        is_data = bool(getattr(image.colorspace_settings, "is_data", False))
        if any(role in {"roughness", "normal"} for role in roles) and not is_data:
            warnings.append(
                issue(
                    "data_texture_colorspace",
                    f"Image {image.name} should use a Non-Color data colorspace",
                    image=image.name,
                    roles=roles,
                    colorspace=image.colorspace_settings.name,
                )
            )
        if any(role in {"base_color", "emission"} for role in roles) and is_data:
            warnings.append(
                issue(
                    "color_texture_colorspace",
                    f"Image {image.name} should use an sRGB color colorspace",
                    image=image.name,
                    roles=roles,
                    colorspace=image.colorspace_settings.name,
                )
            )

    return errors, warnings, textures, used_images


def inspect_geometry(obj: Any, depsgraph: Any) -> Dict[str, Any]:
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        coordinates = [vertex.co.copy() for vertex in mesh.vertices]
        if coordinates:
            minimum = [min(coordinate[axis] for coordinate in coordinates) for axis in range(3)]
            maximum = [max(coordinate[axis] for coordinate in coordinates) for axis in range(3)]
        else:
            minimum = [0.0, 0.0, 0.0]
            maximum = [0.0, 0.0, 0.0]
        triangles = sum(max(0, len(polygon.vertices) - 2) for polygon in mesh.polygons)
        return {
            "vertices": len(mesh.vertices),
            "polygons": len(mesh.polygons),
            "triangles": triangles,
            "uv_layers": len(mesh.uv_layers),
            "local_bounds_min": minimum,
            "local_bounds_max": maximum,
        }
    finally:
        evaluated.to_mesh_clear()


def validate_asset(
    obj: Any,
    category: str,
    prefix: str,
    config: Dict[str, Any],
    depsgraph: Any,
) -> Tuple[Dict[str, Any], Set[Any]]:
    thresholds = config["thresholds"]
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    used_images: Set[Any] = set()

    name_pattern = rf"^{re.escape(prefix)}_\d{{2,}}$"
    if not re.fullmatch(name_pattern, obj.name):
        errors.append(
            issue(
                "invalid_asset_name",
                f"Object {obj.name} does not match {prefix}_ followed by at least two digits",
                object=obj.name,
                expected_pattern=name_pattern,
            )
        )

    if obj.type != "MESH":
        errors.append(
            issue(
                "asset_not_mesh",
                f"Object {obj.name} in {category} is {obj.type}, not MESH",
                object=obj.name,
                object_type=obj.type,
            )
        )
        result = {
            "status": status_for(errors, warnings),
            "category": category,
            "object_name": obj.name,
            "errors": errors,
            "warnings": warnings,
        }
        return result, used_images

    expected_mesh_name = f"{obj.name}_Mesh"
    if obj.data.name != expected_mesh_name:
        warnings.append(
            issue(
                "noncanonical_mesh_name",
                f"Mesh datablock {obj.data.name} should ideally be named {expected_mesh_name}",
                mesh=obj.data.name,
                expected=expected_mesh_name,
            )
        )

    epsilon = float(thresholds["transform_epsilon"])
    if any(abs(float(component) - 1.0) > epsilon for component in obj.scale):
        errors.append(
            issue(
                "unapplied_scale",
                f"Object {obj.name} scale is not 1, 1, 1",
                scale=rounded_vector(obj.scale),
                tolerance=epsilon,
            )
        )

    quaternion = obj.matrix_basis.to_quaternion().normalized()
    rotation_angle = 2.0 * math.acos(min(1.0, abs(float(quaternion.w))))
    if rotation_angle > epsilon:
        errors.append(
            issue(
                "unapplied_rotation",
                f"Object {obj.name} has non-zero rotation",
                rotation_euler_radians=rounded_vector(obj.rotation_euler),
                rotation_angle_radians=round(rotation_angle, 8),
                tolerance=epsilon,
            )
        )

    geometry = inspect_geometry(obj, depsgraph)
    if geometry["vertices"] == 0 or geometry["polygons"] == 0:
        errors.append(issue("empty_mesh", f"Object {obj.name} has no renderable geometry"))
    if geometry["uv_layers"] == 0:
        errors.append(issue("missing_uv_map", f"Object {obj.name} has no UV map"))
    if geometry["triangles"] > int(thresholds["triangle_warning"]):
        warnings.append(
            issue(
                "high_triangle_count",
                f"Object {obj.name} exceeds the configured triangle warning",
                triangles=geometry["triangles"],
                threshold=int(thresholds["triangle_warning"]),
            )
        )

    bounds_min = geometry["local_bounds_min"]
    bounds_max = geometry["local_bounds_max"]
    local_size = [bounds_max[index] - bounds_min[index] for index in range(3)]
    center = [
        (bounds_min[index] + bounds_max[index]) / 2.0 for index in range(3)
    ]
    ground_offset = float(bounds_min[2])
    ground_warning = float(thresholds["origin_ground_warning_m"])
    ground_error = float(thresholds["origin_ground_error_m"])
    if abs(ground_offset) > ground_error:
        errors.append(
            issue(
                "origin_not_at_ground",
                f"Object {obj.name} origin is clearly not at ground level",
                local_ground_z_m=round(ground_offset, 6),
                error_threshold_m=ground_error,
            )
        )
    elif abs(ground_offset) > ground_warning:
        warnings.append(
            issue(
                "origin_slightly_off_ground",
                f"Object {obj.name} origin is slightly off ground level",
                local_ground_z_m=round(ground_offset, 6),
                warning_threshold_m=ground_warning,
            )
        )

    center_absolute = float(thresholds["origin_center_warning_m"])
    center_ratio = float(thresholds["origin_center_warning_ratio"])
    center_tolerances = [
        max(center_absolute, local_size[index] * center_ratio) for index in range(2)
    ]
    if any(abs(center[index]) > center_tolerances[index] for index in range(2)):
        warnings.append(
            issue(
                "origin_off_footprint_center",
                f"Object {obj.name} origin is not near the footprint center",
                local_center_xy_m=rounded_vector(center[:2]),
                tolerances_xy_m=rounded_vector(center_tolerances),
            )
        )

    materials = [slot.material for slot in obj.material_slots]
    if not materials:
        errors.append(issue("missing_material", f"Object {obj.name} has no material"))
    if len(materials) > int(thresholds["material_slot_warning"]):
        warnings.append(
            issue(
                "many_material_slots",
                f"Object {obj.name} has more material slots than expected",
                material_slots=len(materials),
                threshold=int(thresholds["material_slot_warning"]),
            )
        )

    duplicate_named_materials = [
        material.name
        for material in materials
        if material is not None and re.search(r"\.\d{3}$", material.name)
    ]
    if duplicate_named_materials:
        warnings.append(
            issue(
                "duplicate_material_names",
                f"Object {obj.name} uses Blender-suffixed material names",
                materials=sorted(set(duplicate_named_materials)),
            )
        )

    double_sided_materials = [
        material.name
        for material in materials
        if material is not None and material_is_double_sided(material)
    ]
    if double_sided_materials:
        warnings.append(
            issue(
                "double_sided_material",
                f"Object {obj.name} uses materials rendered on both sides",
                materials=sorted(set(double_sided_materials)),
            )
        )

    textures_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for material in materials:
        material_errors, material_warnings, textures, material_images = inspect_material(
            material,
            config["material_requirements"],
            int(thresholds["texture_dimension_warning"]),
        )
        errors.extend(material_errors)
        warnings.extend(material_warnings)
        used_images.update(material_images)
        for texture in textures:
            key = (texture["name"], texture["path"])
            if key not in textures_by_key:
                textures_by_key[key] = texture
            else:
                roles = set(textures_by_key[key]["roles"])
                roles.update(texture["roles"])
                textures_by_key[key]["roles"] = sorted(roles)

    world_dimensions = rounded_vector(obj.dimensions)
    result = {
        "status": status_for(errors, warnings),
        "category": category,
        "object_name": obj.name,
        "mesh_name": obj.data.name,
        "catalogue_location_m": rounded_vector(obj.location),
        "rotation_euler_radians": rounded_vector(obj.rotation_euler),
        "scale": rounded_vector(obj.scale),
        "dimensions_m": {
            "width_x": world_dimensions[0],
            "depth_y": world_dimensions[1],
            "height_z": world_dimensions[2],
        },
        "geometry": {
            "vertices": geometry["vertices"],
            "polygons": geometry["polygons"],
            "triangles": geometry["triangles"],
            "uv_layers": geometry["uv_layers"],
        },
        "origin": {
            "local_ground_z_m": round(ground_offset, 6),
            "local_footprint_center_xy_m": rounded_vector(center[:2]),
        },
        "materials": [material.name if material else None for material in materials],
        "textures": sorted(textures_by_key.values(), key=lambda item: item["name"]),
        "errors": errors,
        "warnings": warnings,
    }
    return result, used_images


def validate_scene(config: Dict[str, Any]) -> Dict[str, Any]:
    global_errors: List[Dict[str, Any]] = []
    global_warnings: List[Dict[str, Any]] = []
    assets: Dict[str, Dict[str, Any]] = {}
    memberships: Dict[Any, List[str]] = {}
    used_images: Set[Any] = set()
    depsgraph = bpy.context.evaluated_depsgraph_get()

    for category, prefix in config["collections"].items():
        collection = bpy.data.collections.get(category)
        if collection is None:
            global_errors.append(
                issue(
                    "missing_collection",
                    f"Required collection {category} does not exist",
                    collection=category,
                )
            )
            continue
        collection_objects = sorted(collection.all_objects, key=lambda item: item.name)
        if not collection_objects:
            global_errors.append(
                issue(
                    "empty_collection",
                    f"Required collection {category} contains no objects",
                    collection=category,
                )
            )
        for obj in collection_objects:
            memberships.setdefault(obj, []).append(category)
            asset, asset_images = validate_asset(obj, category, prefix, config, depsgraph)
            key = obj.name
            if key in assets:
                key = f"{category}/{obj.name}"
            assets[key] = asset
            used_images.update(asset_images)

    for obj, categories in memberships.items():
        if len(categories) > 1:
            global_errors.append(
                issue(
                    "asset_in_multiple_categories",
                    f"Object {obj.name} belongs to multiple release categories",
                    object=obj.name,
                    categories=sorted(categories),
                )
            )

    any_asset_pattern = re.compile(r"^(?:RES|COM|SKY)_\d{2,}$")
    for obj in bpy.data.objects:
        if obj.type == "MESH" and any_asset_pattern.fullmatch(obj.name) and obj not in memberships:
            global_errors.append(
                issue(
                    "asset_outside_release_collections",
                    f"Asset-like object {obj.name} is outside the configured release collections",
                    object=obj.name,
                )
            )

    for image in bpy.data.images:
        if image in used_images or image.name in {"Render Result", "Viewer Node"}:
            continue
        if image.source in {"FILE", "TILED", "SEQUENCE", "MOVIE"} and image.filepath:
            if not image_path_exists(image):
                global_warnings.append(
                    issue(
                        "unused_broken_image_reference",
                        f"Unused image datablock {image.name} points to a missing file",
                        image=image.name,
                        path=image_display_path(image),
                    )
                )

    asset_error_count = sum(len(asset["errors"]) for asset in assets.values())
    asset_warning_count = sum(len(asset["warnings"]) for asset in assets.values())
    error_count = len(global_errors) + asset_error_count
    warning_count = len(global_warnings) + asset_warning_count
    pass_count = sum(asset["status"] == "pass" for asset in assets.values())
    warning_asset_count = sum(asset["status"] == "warning" for asset in assets.values())
    error_asset_count = sum(asset["status"] == "error" for asset in assets.values())
    source_path = Path(bpy.data.filepath) if bpy.data.filepath else Path("unsaved.blend")

    return {
        "schema_version": int(config["schema_version"]),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status_for([None] * error_count, [None] * warning_count),
        "source_blend": display_path(source_path),
        "blender_version": bpy.app.version_string,
        "summary": {
            "asset_count": len(assets),
            "pass_asset_count": pass_count,
            "warning_asset_count": warning_asset_count,
            "error_asset_count": error_asset_count,
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "global": {
            "errors": global_errors,
            "warnings": global_warnings,
        },
        "assets": assets,
    }


def main() -> int:
    arguments = parse_arguments(blender_script_arguments())
    config_path = resolve_from_repository(arguments.config)
    output_path = resolve_from_repository(arguments.output)
    config = deep_merge(DEFAULT_CONFIG, load_json(config_path))
    report = validate_scene(config)
    write_json_atomic(output_path, report)
    summary = report["summary"]
    print(
        "Validation {status}: {assets} assets, {errors} errors, {warnings} warnings".format(
            status=report["status"].upper(),
            assets=summary["asset_count"],
            errors=summary["error_count"],
            warnings=summary["warning_count"],
        )
    )
    print(f"Validation report: {display_path(output_path)}")
    if arguments.fail_on_errors and report["status"] == "error":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
