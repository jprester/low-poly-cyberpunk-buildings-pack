"""Build JSON and CSV manifests from one canonical list of asset records."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from common import display_path, write_json_atomic, write_text_atomic


CSV_FIELDS = [
    "id",
    "category",
    "filename",
    "width_m",
    "depth_m",
    "height_m",
    "vertices",
    "triangles",
    "uv_layers",
    "material_count",
    "materials",
    "texture_families",
    "texture_references",
    "glb_size_bytes",
    "glb_size_mb",
    "validation_status",
    "validation_warning_codes",
]


def build_asset_records(
    validation_report: Dict[str, Any],
    exported_assets: Dict[str, Dict[str, Any]],
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    canonical_materials = set(config["material_requirements"])

    for asset_id, asset in validation_report["assets"].items():
        if asset_id not in exported_assets:
            raise ValueError(f"Export result is missing validated asset {asset_id}")
        exported = exported_assets[asset_id]
        materials = [name for name in asset["materials"] if name]
        texture_families = [name for name in materials if name in canonical_materials]
        texture_references = sorted({texture["name"] for texture in asset["textures"]})
        dimensions = asset["dimensions_m"]
        geometry = asset["geometry"]
        size_bytes = int(exported["size_bytes"])
        warning_codes = sorted({warning["code"] for warning in asset["warnings"]})

        records.append(
            {
                "id": asset_id,
                "category": asset["category"],
                "filename": f"{asset_id}.glb",
                "width_m": dimensions["width_x"],
                "depth_m": dimensions["depth_y"],
                "height_m": dimensions["height_z"],
                "vertices": geometry["vertices"],
                "triangles": geometry["triangles"],
                "uv_layers": geometry["uv_layers"],
                "material_count": len(materials),
                "materials": materials,
                "texture_families": texture_families,
                "texture_references": texture_references,
                "glb_size_bytes": size_bytes,
                "glb_size_mb": round(size_bytes / (1024 * 1024), 3),
                "validation_status": asset["status"],
                "validation_warning_codes": warning_codes,
            }
        )
    return records


def csv_from_records(records: List[Dict[str, Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        row = dict(record)
        for field in (
            "materials",
            "texture_families",
            "texture_references",
            "validation_warning_codes",
        ):
            row[field] = "; ".join(row[field])
        writer.writerow({field: row[field] for field in CSV_FIELDS})
    return buffer.getvalue()


def write_release_manifest(
    output_directory: Path,
    validation_report: Dict[str, Any],
    exported_assets: Dict[str, Dict[str, Any]],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    records = build_asset_records(validation_report, exported_assets, config)
    json_path = output_directory / "asset_manifest.json"
    csv_path = output_directory / "asset_manifest.csv"
    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_blend": validation_report["source_blend"],
        "blender_version": validation_report["blender_version"],
        "asset_count": len(records),
        "assets": records,
    }
    write_json_atomic(json_path, manifest)
    write_text_atomic(csv_path, csv_from_records(records))
    return {
        "status": "pass",
        "asset_count": len(records),
        "json_path": display_path(json_path),
        "csv_path": display_path(csv_path),
    }
