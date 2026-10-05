#!/usr/bin/env python3
"""Download and regenerate the bundled Night City map data.

The updater is intentionally dependency-free. It downloads MapGenie's public
Night City page and map-data response, normalizes them, and atomically updates
the deterministic JSON files consumed by the frontend.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MAP_ID = 115
MAP_SLUG = "night-city"
GAME_SLUG = "cyberpunk-2077"
MAP_PAGE_URL = f"https://mapgenie.io/{GAME_SLUG}/maps/{MAP_SLUG}"
MAP_DATA_URL = f"https://mapgenie.io/api/v1/maps/{MAP_ID}/data"
LOCATION_LINK_RE = re.compile(r"[?&]locationIds?=(\d+)")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")
REQUEST_HEADERS = {
    "Accept-Encoding": "identity",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and update the bundled Night City marker and detail data."
    )
    parser.add_argument(
        "--page-url",
        default=MAP_PAGE_URL,
        help=f"Map page containing configuration metadata (default: {MAP_PAGE_URL})",
    )
    parser.add_argument(
        "--data-url",
        default=MAP_DATA_URL,
        help=f"Public map-data endpoint (default: {MAP_DATA_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout in seconds for each HTTP request (default: 30)",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root containing assets/data (default: inferred from this script)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and print a summary without writing files",
    )
    return parser.parse_args()


def fetch_text(url: str, *, accept: str, timeout: float) -> str:
    request = Request(url, headers={**REQUEST_HEADERS, "Accept": accept})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            content_encoding = (response.headers.get("Content-Encoding") or "identity").lower()
            if content_encoding == "gzip":
                payload = gzip.decompress(payload)
            elif content_encoding not in {"identity", ""}:
                raise ValueError(f"GET {url} returned unsupported encoding: {content_encoding}")
            charset = response.headers.get_content_charset() or "utf-8"
            return payload.decode(charset)
    except HTTPError as error:
        raise ValueError(f"GET {url} failed with HTTP {error.code}") from error
    except URLError as error:
        raise ValueError(f"GET {url} failed: {error.reason}") from error


def extract_js_json(source: str, prefix: str) -> object:
    start = source.find(prefix)
    if start < 0:
        raise ValueError(f"Embedded value not found in map page: {prefix.strip()}")
    start += len(prefix)
    while start < len(source) and source[start].isspace():
        start += 1
    value, _end = json.JSONDecoder().raw_decode(source[start:])
    return value


def scaled_icon(sprite: dict | None) -> dict | None:
    if not sprite:
        return None
    ratio = sprite.get("pixelRatio") or 1
    width = sprite["width"] / ratio
    height = sprite["height"] / ratio

    def clean_number(value: float) -> int | float:
        return int(value) if float(value).is_integer() else value

    return {
        "width": clean_number(width),
        "height": clean_number(height),
        "anchorX": clean_number(width / 2),
        "anchorY": clean_number(height),
        "offsetX": clean_number(sprite["x"] / ratio),
        "offsetY": clean_number(sprite["y"] / ratio),
        "pixelRatio": 1,
    }


def sanitize_media(media: object) -> list[dict]:
    if not isinstance(media, list):
        return []
    result = []
    for item in media:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        result.append(
            {
                "id": item.get("id"),
                "title": item.get("title") or "",
                "url": item["url"],
                "type": item.get("type"),
                "mimeType": item.get("mime_type"),
                "attribution": item.get("attribution") or "",
                "order": item.get("order"),
            }
        )
    return result


def sanitize_color(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and HEX_COLOR_RE.fullmatch(value) else fallback


def normalize_regions(api_payload: dict) -> list[dict]:
    source_regions = api_payload.get("regions")
    if not isinstance(source_regions, list) or not source_regions:
        raise ValueError("Map data response contains no regions")

    source_styles = api_payload.get("styles", {}).get("regionStyles", {})
    if not isinstance(source_styles, dict):
        source_styles = {}

    regions = []
    for source in source_regions:
        region_id = source.get("id")
        title = source.get("title")
        if region_id is None or not isinstance(title, str) or not title.strip():
            raise ValueError("Map data response contains a region without an id or title")

        features = []
        for feature in source.get("features") or []:
            geometry = feature.get("geometry") if isinstance(feature, dict) else None
            if not isinstance(geometry, dict):
                continue
            geometry_type = geometry.get("type")
            coordinates = geometry.get("coordinates")
            if geometry_type not in {"Polygon", "MultiPolygon"} or not isinstance(coordinates, list):
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": geometry_type, "coordinates": coordinates},
                    "properties": {"id": region_id},
                }
            )
        if not features:
            raise ValueError(f"Region {region_id} ({title}) contains no polygon geometry")

        center = None
        if source.get("center_x") is not None and source.get("center_y") is not None:
            center = {
                "lat": float(source["center_y"]),
                "lng": float(source["center_x"]),
            }

        style = source_styles.get(str(region_id), {})
        if not isinstance(style, dict):
            style = {}
        regions.append(
            {
                "id": region_id,
                "parentId": source.get("parent_region_id"),
                "name": title.strip(),
                "subtitle": source.get("subtitle"),
                "order": source.get("order", 0),
                "color": sanitize_color(style.get("fill-color"), "#fcee0a"),
                "textColor": sanitize_color(style.get("text-color"), "#eeeddf"),
                "haloColor": sanitize_color(style.get("text-halo-color"), "#111318"),
                "center": center,
                "features": features,
            }
        )

    regions.sort(key=lambda region: (region["order"], region["name"], region["id"]))
    return regions


def build_output(
    api_payload: dict,
    page_html: str,
    current: dict,
    *,
    page_url: str,
    data_url: str,
) -> tuple[dict, dict, dict]:
    map_data = extract_js_json(page_html, "window.mapData = ")
    sprite_positions = extract_js_json(page_html, "const MARKER_SPRITE_POSITIONS_V3 = ")

    if str(map_data.get("map", {}).get("id")) != str(MAP_ID):
        raise ValueError(f"Map page contains map {map_data.get('map', {}).get('id')}, expected {MAP_ID}")

    locations = api_payload.get("locations")
    regions = normalize_regions(api_payload)
    groups = map_data.get("groups")
    tile_sets = map_data.get("mapConfig", {}).get("tile_sets")
    if not isinstance(locations, list) or not locations:
        raise ValueError("Map data response contains no locations")
    if not isinstance(groups, list) or not groups:
        raise ValueError("Map page contains no category groups")
    if not isinstance(tile_sets, list) or not tile_sets:
        raise ValueError("Map page contains no tile sets")

    location_counts = Counter(str(location.get("category_id")) for location in locations)
    category_by_id: dict[str, dict] = {}
    types = []
    for group in groups:
        categories = [
            category
            for category in group.get("categories", [])
            if not category.get("premium")
        ]
        child_slugs = [str(category["id"]) for category in categories]
        types.append(
            {
                "slug": str(group["id"]),
                "name": group["title"],
                "parent": None,
                "isParent": True,
                "childTypes": child_slugs,
                "count": 0,
                "icon": None,
            }
        )
        for category in categories:
            slug = str(category["id"])
            category_by_id[slug] = category
            types.append(
                {
                    "slug": slug,
                    "name": category["title"],
                    "parent": str(group["id"]),
                    "isParent": False,
                    "childTypes": [],
                    "count": location_counts[slug],
                    "icon": scaled_icon(sprite_positions.get(slug)),
                }
            )

    unknown_categories = sorted(
        category_id for category_id in location_counts if category_id not in category_by_id
    )
    if unknown_categories:
        raise ValueError(f"Locations reference unknown/free-hidden categories: {', '.join(unknown_categories)}")

    existing_by_slug = {
        str(marker.get("slug")): marker
        for marker in current.get("markers", [])
        if marker.get("slug") is not None
    }
    markers = []
    details = {}
    for location in locations:
        slug = str(location["id"])
        type_slug = str(location["category_id"])
        category = category_by_id[type_slug]
        previous = existing_by_slug.get(slug, {})
        marker = {
            "id": f"{GAME_SLUG}:{MAP_SLUG}:{slug}:{type_slug}",
            "slug": slug,
            "name": location["title"],
            "type": type_slug,
            "iconSlug": category.get("icon"),
            "lat": float(location["latitude"]),
            "lng": float(location["longitude"]),
            "regionId": location.get("region_id"),
            "checklistTaskId": previous.get("checklistTaskId"),
            "wikiPage": previous.get("wikiPage"),
        }
        markers.append(marker)

        description = location.get("description") or ""
        media = sanitize_media(location.get("media"))
        tags = location.get("tags") if isinstance(location.get("tags"), list) else []
        linked_ids = list(dict.fromkeys(LOCATION_LINK_RE.findall(description)))
        if description.strip() or media or tags:
            details[slug] = {
                "description": description,
                "linkedLocationIds": linked_ids,
                "media": media,
                "tags": tags,
            }

    map_config = map_data["mapConfig"]
    tile_sets = sorted(tile_sets, key=lambda item: item.get("order", 0))
    current_map = current.get("map", {})
    output = {
        "generatedFrom": page_url,
        "dataSource": data_url,
        "map": {
            "name": map_data["map"]["title"],
            "slug": map_data["map"]["slug"],
            "objectName": current_map.get("objectName", "Cyberpunk 2077"),
            "initialZoom": map_config["initial_zoom"],
            "minZoom": max(tile_set["min_zoom"] for tile_set in tile_sets),
            "maxZoom": max(tile_set["max_zoom"] for tile_set in tile_sets),
            "maxNativeZoom": min(tile_set["tiles_max_zoom"] for tile_set in tile_sets),
            "regionDetailZoom": 13,
            "initialLat": map_config["start_lat"],
            "initialLng": map_config["start_lng"],
            "backgroundColor": current_map.get("backgroundColor", "#110b0b"),
            "tilesets": [
                f"https://tiles.mapgenie.io/games/{tile_set['pattern']}" for tile_set in tile_sets
            ],
            "markerSprite": current_map.get("markerSprite", "assets/images/markers@2x.webp"),
        },
        "types": types,
        "regions": regions,
        "markers": markers,
    }
    summary = {
        "locations": len(markers),
        "regions": len(regions),
        "details": len(details),
        "descriptions": sum(bool(detail["description"].strip()) for detail in details.values()),
        "linkedDescriptions": sum(bool(detail["linkedLocationIds"]) for detail in details.values()),
        "mediaLocations": sum(bool(detail["media"]) for detail in details.values()),
        "newLocations": len(set(marker["slug"] for marker in markers) - set(existing_by_slug)),
        "removedLocations": len(set(existing_by_slug) - set(marker["slug"] for marker in markers)),
    }
    return output, details, summary


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    map_path = project_root / "assets" / "data" / "map-data.json"
    details_path = project_root / "assets" / "data" / "location-details.json"
    try:
        with map_path.open("r", encoding="utf-8") as handle:
            current = json.load(handle)
        if details_path.exists():
            with details_path.open("r", encoding="utf-8") as handle:
                current_details = json.load(handle)
        else:
            current_details = {}

        page_html = fetch_text(args.page_url, accept="text/html,application/xhtml+xml", timeout=args.timeout)
        api_text = fetch_text(args.data_url, accept="application/json", timeout=args.timeout)
        api_payload = json.loads(api_text)
        output, details, summary = build_output(
            api_payload,
            page_html,
            current,
            page_url=args.page_url,
            data_url=args.data_url,
        )
        map_changed = output != current
        details_changed = details != current_details
        if not args.check:
            if map_changed:
                write_json(map_path, output)
            if details_changed:
                write_json(details_path, details)
        mode = "Checked" if args.check else "Updated"
        print(f"{mode} Night City data")
        print(f"  page: {args.page_url}")
        print(f"  data: {args.data_url}")
        for key, value in summary.items():
            print(f"  {key}: {value}")
        print(f"  mapDataChanged: {str(map_changed).lower()}")
        print(f"  locationDetailsChanged: {str(details_changed).lower()}")
        if args.check:
            print("  no files written (--check)")
        elif not map_changed and not details_changed:
            print("  no files written (already up to date)")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
