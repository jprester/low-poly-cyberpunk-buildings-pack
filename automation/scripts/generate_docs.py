"""Generate release Markdown documentation from the canonical JSON manifest."""

from __future__ import annotations

import argparse
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


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


REQUIRED_ASSET_FIELDS = {
    "id",
    "category",
    "filename",
    "width_m",
    "depth_m",
    "height_m",
    "vertices",
    "triangles",
    "materials",
    "texture_families",
    "glb_size_bytes",
}


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate release documentation")
    parser.add_argument(
        "--manifest",
        default="build/release/Manifest/asset_manifest.json",
        help="Canonical JSON manifest path",
    )
    parser.add_argument(
        "--readme-template",
        default="automation/templates/README.template.md",
        help="README template path",
    )
    parser.add_argument(
        "--ai-template",
        default="automation/templates/AI_DISCLOSURE.md",
        help="AI disclosure template path",
    )
    parser.add_argument(
        "--output-dir",
        default="build/release/Documentation",
        help="Documentation output directory; it must be inside build",
    )
    parser.add_argument(
        "--report",
        default="build/documentation_report.json",
        help="Machine-readable documentation report path",
    )
    return parser.parse_args(argv)


def validate_manifest(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported or missing manifest schema_version")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("Manifest must contain a non-empty assets list")
    if manifest.get("asset_count") != len(assets):
        raise ValueError("Manifest asset_count does not match its assets list")
    seen_ids = set()
    for index, asset in enumerate(assets):
        missing = sorted(REQUIRED_ASSET_FIELDS - set(asset))
        if missing:
            raise ValueError(f"Manifest asset {index} is missing: {', '.join(missing)}")
        if asset["id"] in seen_ids:
            raise ValueError(f"Duplicate manifest asset ID: {asset['id']}")
        seen_ids.add(asset["id"])
    return assets


def format_decimal(value: float) -> str:
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


def format_range(values: Iterable[float], suffix: str = "") -> str:
    numbers = list(values)
    return f"{format_decimal(min(numbers))}–{format_decimal(max(numbers))}{suffix}"


def format_integer_range(values: Iterable[int]) -> str:
    numbers = list(values)
    return f"{min(numbers):,}–{max(numbers):,}"


def ordered_categories(assets: List[Dict[str, Any]]) -> OrderedDict[str, List[Dict[str, Any]]]:
    categories: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()
    for asset in assets:
        categories.setdefault(asset["category"], []).append(asset)
    return categories


def generated_summary(assets: List[Dict[str, Any]]) -> str:
    categories = ordered_categories(assets)
    category_counts = ", ".join(
        f"{len(items)} {category}" for category, items in categories.items()
    )
    lines = [
        "## Asset summary",
        "",
        f"The pack contains **{len(assets)} buildings**: {category_counts}.",
        "",
        "| Category | Assets | Width | Depth | Height | Triangles |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for category, items in categories.items():
        lines.append(
            "| {category} | {count} | {width} | {depth} | {height} | {triangles} |".format(
                category=category,
                count=len(items),
                width=format_range((item["width_m"] for item in items), " m"),
                depth=format_range((item["depth_m"] for item in items), " m"),
                height=format_range((item["height_m"] for item in items), " m"),
                triangles=format_integer_range(item["triangles"] for item in items),
            )
        )

    all_materials = sorted({name for asset in assets for name in asset["materials"]})
    texture_families = sorted(
        {name for asset in assets for name in asset["texture_families"]}
    )
    total_size_bytes = sum(int(asset["glb_size_bytes"]) for asset in assets)
    lines.extend(
        [
            "",
            "Overall release statistics:",
            "",
            f"- Vertex range: {format_integer_range(asset['vertices'] for asset in assets)}",
            f"- Triangle range: {format_integer_range(asset['triangles'] for asset in assets)}",
            f"- Width range: {format_range((asset['width_m'] for asset in assets), ' m')}",
            f"- Depth range: {format_range((asset['depth_m'] for asset in assets), ' m')}",
            f"- Height range: {format_range((asset['height_m'] for asset in assets), ' m')}",
            f"- Combined self-contained GLB size: {total_size_bytes / (1024 * 1024):.1f} MiB",
            "",
            "Included materials:",
            "",
        ]
    )
    lines.extend(f"- `{name}`" for name in all_materials)
    lines.extend(["", "Shared texture-atlas families:", ""])
    lines.extend(f"- `{name}`" for name in texture_families)
    return "\n".join(lines)


def render_template(template: str, replacements: Dict[str, str]) -> str:
    rendered = template
    for name, value in replacements.items():
        token = "{{" + name + "}}"
        if token not in rendered:
            raise ValueError(f"Template is missing required token {token}")
        rendered = rendered.replace(token, value)
    unresolved = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered)))
    if unresolved:
        raise ValueError(f"Unresolved template token(s): {', '.join(unresolved)}")
    return rendered.rstrip() + "\n"


def ensure_portable(text: str, label: str) -> None:
    forbidden = {str(REPOSITORY_ROOT.resolve()), str(Path.home().resolve())}
    leaked = [value for value in forbidden if value and value in text]
    if leaked:
        raise ValueError(f"{label} contains an absolute local filesystem path")


def main() -> int:
    arguments = parse_arguments(sys.argv[1:])
    manifest_path = resolve_from_repository(arguments.manifest)
    readme_template_path = resolve_from_repository(arguments.readme_template)
    ai_template_path = resolve_from_repository(arguments.ai_template)
    output_directory = resolve_from_repository(arguments.output_dir)
    report_path = resolve_from_repository(arguments.report)
    require_build_path(output_directory, "Documentation output directory")
    require_build_path(report_path, "Documentation report")

    manifest = load_json(manifest_path)
    assets = validate_manifest(manifest)
    readme_template = readme_template_path.read_text(encoding="utf-8")
    ai_disclosure = ai_template_path.read_text(encoding="utf-8").rstrip() + "\n"
    readme = render_template(
        readme_template,
        {"GENERATED_ASSET_SUMMARY": generated_summary(assets)},
    )
    ensure_portable(readme, "Generated README")
    ensure_portable(ai_disclosure, "Generated AI disclosure")

    readme_path = output_directory / "README.md"
    ai_path = output_directory / "AI_DISCLOSURE.md"
    write_text_atomic(readme_path, readme)
    write_text_atomic(ai_path, ai_disclosure)

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "source_manifest": display_path(manifest_path),
        "asset_count": len(assets),
        "outputs": {
            "readme": {
                "path": display_path(readme_path),
                "size_bytes": readme_path.stat().st_size,
            },
            "ai_disclosure": {
                "path": display_path(ai_path),
                "size_bytes": ai_path.stat().st_size,
            },
        },
    }
    write_json_atomic(report_path, report)
    print(f"Documentation PASS: {len(assets)} manifest assets")
    print(f"README: {display_path(readme_path)}")
    print(f"AI disclosure: {display_path(ai_path)}")
    print(f"Documentation report: {display_path(report_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
