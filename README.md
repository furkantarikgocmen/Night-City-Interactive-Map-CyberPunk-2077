# Night City Interactive Map

A self-hosted interactive map for Cyberpunk 2077 collectors who want to track everything they discover across Night City without a subscription or an arbitrary found-item limit.

The application includes 2,577 locations across 52 marker types, rich location descriptions with cross-map navigation, category filters, text search, standard and satellite map layers, persistent found status, custom markers, and JSON backup/restore.

## Screenshots

### Standard map and category filters

![Night City standard map with category filters](docs/screenshots/map-view.png)

### Satellite layer and found-location tracking

![Night City satellite map with a found iconic weapon](docs/screenshots/satellite-view.png)

## Features

- Interactive Night City map with standard and satellite layers
- 2,577 built-in locations organized into 52 marker types
- Rich location descriptions and clickable links between related locations
- Search and category filters
- Unlimited found-location tracking
- Add, edit, and delete personal map markers
- Import and export progress as JSON
- Persistent SQLite storage instead of browser sessions
- Single-user, authentication-free setup for personal use
- Self-hosted with Docker Compose, Traefik, and Nginx
- Automatic Let's Encrypt TLS certificates and renewal
- Automatic HTTP-to-HTTPS redirect with HTTP/2 support
- Responsive desktop and mobile interface

## Quick start

### Requirements

- Docker
- Docker Compose

### Run locally

No domain or environment file is required for local use:

```bash
docker compose up --build -d
```

Open <http://localhost:8081>.

### Run with automatic TLS

Copy the example environment file:

```bash
cp .env.example .env
```

PowerShell equivalent:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set your public hostname and Let's Encrypt account email:

```dotenv
DOMAIN=night-city.example.com
LETSENCRYPT_EMAIL=you@example.com
COMPOSE_PROFILES=tls
```

Before starting the stack, make sure:

- The domain's `A` and/or `AAAA` record points to this server.
- TCP ports `80` and `443` are reachable from the public internet.
- No other service on the host is already using ports `80` or `443`.

Start the stack with the same command:

```bash
docker compose up --build -d
```

Open `https://<your-domain>`. Traefik obtains the certificate from Let's Encrypt, redirects HTTP traffic to HTTPS, renews the certificate automatically, and negotiates HTTP/2 with supported clients.

> [!NOTE]
> Let's Encrypt does not issue certificates for `localhost`, private IP addresses, or hostnames that are not publicly reachable. A real public domain is required for this HTTP-01 setup.

### Docker Compose profiles

The default Compose profile starts only the application and SQLite API for local use on `localhost:8081`. Traefik belongs to the optional `tls` profile.

Setting the following value in `.env` activates that profile automatically whenever you run the normal Compose command:

```dotenv
COMPOSE_PROFILES=tls
```

You can also activate it explicitly without setting `COMPOSE_PROFILES`:

```bash
docker compose --profile tls up --build -d
```

When the `tls` profile is active, `DOMAIN` and `LETSENCRYPT_EMAIL` must contain real production values.

To stop the application:

```bash
docker compose down
```

Your progress is stored in the `night-city-data` Docker volume. Certificates and ACME account data are stored in the `traefik-certificates` volume. Both survive container recreation and `docker compose down`.

> [!WARNING]
> Running `docker compose down -v` also removes the SQLite volume and all saved progress. Export a JSON backup first if you need to preserve it.

## Updating

After pulling a newer version, rebuild the containers:

```bash
git pull
docker compose up --build -d
```

The existing SQLite volume will be reused.

### Refresh the bundled map data

The dependency-free updater downloads the public Night City page and map-data response directly from MapGenie. No browser export, HAR file, cookies, or account credentials are needed.

Validate the current upstream data without changing any files:

```bash
python3 tools/update_mapgenie_data.py --check
```

Regenerate the bundled files:

```bash
python3 tools/update_mapgenie_data.py
```

If Python is not installed on the host, use the project's API image:

```bash
docker compose run --rm --no-deps \
  -v "$PWD:/work" -w /work night-city-api \
  python tools/update_mapgenie_data.py --check
```

The updater reads configuration and sprite metadata embedded in:

```text
https://mapgenie.io/cyberpunk-2077/maps/night-city
```

and location data from:

```text
https://mapgenie.io/api/v1/maps/115/data
```

It deterministically regenerates `assets/data/map-data.json` and `assets/data/location-details.json`. This includes map settings, categories, sprite positions, markers, descriptions, related-location links, tags, and media metadata. Premium categories are excluded, invalid or inconsistent responses fail before replacing existing data, and unchanged output is not rewritten. The default source URLs are declared at the top of the script and can also be overridden with `--page-url` and `--data-url`.

## Architecture

| Component | Purpose |
| --- | --- |
| Traefik | Terminates TLS, obtains and renews Let's Encrypt certificates, redirects HTTP to HTTPS, and serves HTTP/2 |
| Nginx | Serves the frontend, local map details, and marker data, and proxies `/api` requests on the private Docker network |
| Python service | Provides the small REST API using only the Python standard library |
| SQLite | Stores found locations and custom markers |
| Docker Compose | Runs the frontend and API services and manages persistent storage |

In TLS mode, Traefik exposes public ports `80` and `443`. Nginx also binds to `127.0.0.1:8081` for host-local access, while the API remains available only on the private Docker network. The frontend, API, marker data, and marker sprite are served locally. Map tile images are requested from `tiles.mapgenie.io`, so displaying the map background currently requires an internet connection.

## Verify TLS and HTTP/2

After Let's Encrypt has issued the certificate:

```bash
curl -I --http2 https://night-city.example.com
```

The status line should report HTTP/2. Certificate events can be inspected with:

```bash
docker compose logs traefik
```

## API

The found-location routes follow the same basic shape used by the original map:

```text
GET    /api/v1/user/map-data/115
PUT    /api/v1/user/locations/:locationId
DELETE /api/v1/user/locations/:locationId
DELETE /api/v1/user/locations?mapId=115
```

Custom marker and backup routes:

```text
GET    /api/v1/user/custom-markers?mapId=115
POST   /api/v1/user/custom-markers
PUT    /api/v1/user/custom-markers/:id
DELETE /api/v1/user/custom-markers/:id?mapId=115
POST   /api/v1/user/import
```

Example:

```bash
curl -X PUT http://localhost:8081/api/v1/user/locations/605347 \
  -H "Content-Type: application/json" \
  -d '{"mapId":115}'
```

## Data and trademarks

This is an unofficial, fan-made project intended for personal use. It is not affiliated with or endorsed by CD PROJEKT RED, IGN, or MapGenie. Cyberpunk 2077 and related names and marks belong to their respective owners.

The bundled marker dataset was derived from information publicly available through the referenced interactive map. Do not use this project to access restricted or paid content.
