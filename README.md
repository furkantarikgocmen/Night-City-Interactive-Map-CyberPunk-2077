# Night City Interactive Map

A self-hosted interactive map for Cyberpunk 2077 collectors who want to track everything they discover across Night City without a subscription or an arbitrary found-item limit.

The application includes 2,566 locations across 58 marker types, category filters, text search, standard and satellite map layers, persistent found status, custom markers, and JSON backup/restore.

## Features

- Interactive Night City map with standard and satellite layers
- 2,566 built-in locations organized into 58 marker types
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

### Run the application

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
```

Before starting the stack, make sure:

- The domain's `A` and/or `AAAA` record points to this server.
- TCP ports `80` and `443` are reachable from the public internet.
- No other service on the host is already using ports `80` or `443`.

Start the stack:

```bash
docker compose up --build -d
```

Open `https://<your-domain>`. Traefik obtains the certificate from Let's Encrypt, redirects HTTP traffic to HTTPS, renews the certificate automatically, and negotiates HTTP/2 with supported clients.

> [!NOTE]
> Let's Encrypt does not issue certificates for `localhost`, private IP addresses, or hostnames that are not publicly reachable. A real public domain is required for this HTTP-01 setup.

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

## Architecture

| Component | Purpose |
| --- | --- |
| Traefik | Terminates TLS, obtains and renews Let's Encrypt certificates, redirects HTTP to HTTPS, and serves HTTP/2 |
| Nginx | Serves the frontend and proxies `/api` requests on the private Docker network |
| Python service | Provides the small REST API using only the Python standard library |
| SQLite | Stores found locations and custom markers |
| Docker Compose | Runs the frontend and API services and manages persistent storage |

Only Traefik exposes host ports. Nginx and the API stay on the private Docker network. The frontend, API, marker data, and marker sprite are served locally. Map tile images are requested from `tiles.mapgenie.io`, so displaying the map background currently requires an internet connection.

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
