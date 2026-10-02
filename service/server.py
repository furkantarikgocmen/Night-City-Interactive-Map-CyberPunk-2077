import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse


DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/night-city.db")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
DEFAULT_MAP_ID = 115


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize_database():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS marked_locations (
                map_id INTEGER NOT NULL,
                location_id TEXT NOT NULL,
                found INTEGER NOT NULL DEFAULT 1 CHECK (found IN (0, 1)),
                updated_at TEXT NOT NULL,
                PRIMARY KEY (map_id, location_id)
            );

            CREATE TABLE IF NOT EXISTS custom_markers (
                id TEXT PRIMARY KEY,
                map_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type_slug TEXT NOT NULL DEFAULT 'custom',
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_marked_locations_map
                ON marked_locations (map_id);
            CREATE INDEX IF NOT EXISTS idx_custom_markers_map
                ON custom_markers (map_id);
            """
        )


def marker_from_row(row):
    return {
        "id": row["id"],
        "mapId": row["map_id"],
        "name": row["name"],
        "type": row["type_slug"],
        "lat": row["latitude"],
        "lng": row["longitude"],
        "notes": row["notes"],
        "regionId": None,
        "custom": True,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def validate_marker(payload, marker_id=None):
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")
    if len(name) > 100:
        raise ValueError("name must be 100 characters or fewer")
    try:
        latitude = float(payload["lat"])
        longitude = float(payload["lng"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("lat and lng must be numbers")
    return {
        "id": marker_id or str(payload.get("id") or f"custom:{uuid.uuid4().hex}"),
        "map_id": int(payload.get("mapId", DEFAULT_MAP_ID)),
        "name": name,
        "type_slug": str(payload.get("type") or "custom"),
        "latitude": latitude,
        "longitude": longitude,
        "notes": str(payload.get("notes") or "")[:500],
    }


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "NightCityLocal/1.0"

    def log_message(self, format_string, *args):
        print(f"{self.address_string()} - {format_string % args}")

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000:
            raise ValueError("request body is too large")
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def route(self):
        parsed = urlparse(self.path)
        return parsed.path, parse_qs(parsed.query)

    def map_id_from(self, query, payload=None):
        if payload and "mapId" in payload:
            return int(payload["mapId"])
        return int(query.get("mapId", [DEFAULT_MAP_ID])[0])

    def do_GET(self):
        path, query = self.route()
        if path == "/healthz":
            return self.send_json(200, {"status": "ok"})

        match = re.fullmatch(r"/api/v1/user/map-data/(\d+)", path)
        if match:
            map_id = int(match.group(1))
            with connect() as db:
                rows = db.execute(
                    "SELECT location_id FROM marked_locations WHERE map_id = ? AND found = 1",
                    (map_id,),
                ).fetchall()
            locations = {row["location_id"]: True for row in rows}
            return self.send_json(200, {
                "locations": locations,
                "gameLocationsCount": len(locations),
                "hasPro": False,
                "trackedCategoryIds": [],
                "suggestions": [],
                "presets": None,
                "notes": [],
                "maxMarkedLocations": 100000,
                "profiles": [],
                "profileId": None,
            })

        if path == "/api/v1/user/custom-markers":
            map_id = self.map_id_from(query)
            with connect() as db:
                rows = db.execute(
                    "SELECT * FROM custom_markers WHERE map_id = ? ORDER BY created_at",
                    (map_id,),
                ).fetchall()
            return self.send_json(200, {"markers": [marker_from_row(row) for row in rows]})

        return self.send_json(404, {"error": "not found"})

    def do_PUT(self):
        path, query = self.route()
        location_match = re.fullmatch(r"/api/v1/user/locations/([^/]+)", path)
        marker_match = re.fullmatch(r"/api/v1/user/custom-markers/([^/]+)", path)
        try:
            payload = self.read_json()
            if location_match:
                location_id = unquote(location_match.group(1))
                map_id = self.map_id_from(query, payload)
                with connect() as db:
                    db.execute(
                        """INSERT INTO marked_locations (map_id, location_id, found, updated_at)
                           VALUES (?, ?, 1, ?)
                           ON CONFLICT(map_id, location_id)
                           DO UPDATE SET found = 1, updated_at = excluded.updated_at""",
                        (map_id, location_id, utc_now()),
                    )
                return self.send_json(200, {"locationId": location_id, "found": True})

            if marker_match:
                marker_id = unquote(marker_match.group(1))
                marker = validate_marker(payload, marker_id)
                now = utc_now()
                with connect() as db:
                    existing = db.execute("SELECT created_at FROM custom_markers WHERE id = ?", (marker_id,)).fetchone()
                    if not existing:
                        return self.send_json(404, {"error": "custom marker not found"})
                    db.execute(
                        """UPDATE custom_markers
                           SET map_id = ?, name = ?, type_slug = ?, latitude = ?, longitude = ?, notes = ?, updated_at = ?
                           WHERE id = ?""",
                        (marker["map_id"], marker["name"], marker["type_slug"], marker["latitude"], marker["longitude"], marker["notes"], now, marker_id),
                    )
                    row = db.execute("SELECT * FROM custom_markers WHERE id = ?", (marker_id,)).fetchone()
                return self.send_json(200, marker_from_row(row))
        except (ValueError, json.JSONDecodeError) as error:
            return self.send_json(400, {"error": str(error)})
        return self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path, _query = self.route()
        try:
            payload = self.read_json()
            if path == "/api/v1/user/custom-markers":
                marker = validate_marker(payload)
                now = utc_now()
                with connect() as db:
                    db.execute(
                        """INSERT INTO custom_markers
                           (id, map_id, name, type_slug, latitude, longitude, notes, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (marker["id"], marker["map_id"], marker["name"], marker["type_slug"], marker["latitude"], marker["longitude"], marker["notes"], now, now),
                    )
                    row = db.execute("SELECT * FROM custom_markers WHERE id = ?", (marker["id"],)).fetchone()
                return self.send_json(201, marker_from_row(row))

            if path == "/api/v1/user/import":
                map_id = int(payload.get("mapId", DEFAULT_MAP_ID))
                locations = [str(value) for value in payload.get("found", [])]
                custom_values = payload.get("custom", [])
                if not isinstance(custom_values, list) or not all(isinstance(value, dict) for value in custom_values):
                    raise ValueError("custom must be an array of marker objects")
                markers = [validate_marker({**value, "mapId": map_id}, value.get("id")) for value in custom_values]
                now = utc_now()
                with connect() as db:
                    db.execute("DELETE FROM marked_locations WHERE map_id = ?", (map_id,))
                    db.execute("DELETE FROM custom_markers WHERE map_id = ?", (map_id,))
                    db.executemany(
                        "INSERT INTO marked_locations (map_id, location_id, found, updated_at) VALUES (?, ?, 1, ?)",
                        [(map_id, location_id, now) for location_id in locations],
                    )
                    db.executemany(
                        """INSERT INTO custom_markers
                           (id, map_id, name, type_slug, latitude, longitude, notes, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [(marker["id"], map_id, marker["name"], marker["type_slug"], marker["latitude"], marker["longitude"], marker["notes"], now, now) for marker in markers],
                    )
                return self.send_json(200, {"locations": len(locations), "customMarkers": len(markers)})
        except (ValueError, json.JSONDecodeError, sqlite3.IntegrityError) as error:
            return self.send_json(400, {"error": str(error)})
        return self.send_json(404, {"error": "not found"})

    def do_DELETE(self):
        path, query = self.route()
        location_match = re.fullmatch(r"/api/v1/user/locations/([^/]+)", path)
        marker_match = re.fullmatch(r"/api/v1/user/custom-markers/([^/]+)", path)
        try:
            payload = self.read_json()
            map_id = self.map_id_from(query, payload)
            if location_match:
                location_id = unquote(location_match.group(1))
                with connect() as db:
                    db.execute("DELETE FROM marked_locations WHERE map_id = ? AND location_id = ?", (map_id, location_id))
                return self.send_json(200, {"locationId": location_id, "found": False})

            if path == "/api/v1/user/locations":
                with connect() as db:
                    cursor = db.execute("DELETE FROM marked_locations WHERE map_id = ?", (map_id,))
                return self.send_json(200, {"deleted": cursor.rowcount})

            if marker_match:
                marker_id = unquote(marker_match.group(1))
                with connect() as db:
                    cursor = db.execute("DELETE FROM custom_markers WHERE map_id = ? AND id = ?", (map_id, marker_id))
                if cursor.rowcount == 0:
                    return self.send_json(404, {"error": "custom marker not found"})
                return self.send_json(200, {"id": marker_id, "deleted": True})
        except (ValueError, json.JSONDecodeError) as error:
            return self.send_json(400, {"error": str(error)})
        return self.send_json(404, {"error": "not found"})


if __name__ == "__main__":
    initialize_database()
    server = ThreadingHTTPServer((HOST, PORT), ApiHandler)
    print(f"Night City API listening on {HOST}:{PORT}; database={DATABASE_PATH}")
    server.serve_forever()
