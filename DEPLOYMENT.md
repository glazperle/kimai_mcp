# Kimai MCP Server - Zentrales Deployment

Dieses Dokument beschreibt, wie Sie den Kimai MCP Server zentral in Ihrem Unternehmen bereitstellen können, sodass Sie ihn nicht auf jedem Client lokal installieren müssen.

## Überblick

Anstatt den MCP Server auf jedem Client zu installieren, können Sie ihn einmal zentral als HTTP/SSE-Server bereitstellen. Alle Clients (Claude Desktop, etc.) verbinden sich dann über HTTP zu diesem zentralen Server.

### Vorteile

- ✅ **Einmalige Installation**: Server nur einmal installieren und konfigurieren
- ✅ **Zentrale Verwaltung**: Einfache Updates und Wartung an einem Ort
- ✅ **Sicherheit**: Token-basierte Authentifizierung für Unternehmensnetzwerke
- ✅ **Skalierbar**: Kann mehrere Clients gleichzeitig bedienen
- ✅ **Docker-Support**: Einfaches Deployment mit Docker/Docker Compose

## Deployment-Optionen

### Option 1: Docker Compose (Empfohlen)

Die einfachste Methode für Produktionsumgebungen.

#### 1. Voraussetzungen

```bash
# Docker und Docker Compose installiert
docker --version
docker-compose --version
```

#### 2. Konfiguration

```bash
# Repository klonen
git clone https://github.com/glazperle/kimai_mcp.git
cd kimai_mcp

# Umgebungsvariablen konfigurieren
cp .env.server.example .env
nano .env  # oder vim, code, etc.
```

Erforderliche Einstellungen in `.env`:

```bash
# ERFORDERLICH
KIMAI_URL=https://ihre-kimai-instanz.de
KIMAI_API_TOKEN=ihr-kimai-api-token

# OPTIONAL (wird automatisch generiert wenn nicht gesetzt)
MCP_SERVER_TOKEN=ihr-sicherer-token

# OPTIONAL
KIMAI_DEFAULT_USER=1
SERVER_PORT=8000
```

#### 3. Server starten

```bash
# Server im Hintergrund starten
docker-compose up -d

# Logs ansehen
docker-compose logs -f

# Token finden (wenn automatisch generiert)
docker-compose logs | grep "Generated new authentication token"
```

#### 4. Server testen

```bash
# Health Check
curl http://localhost:8000/health

# Erwartete Antwort:
# {
#   "status": "healthy",
#   "version": "2.6.0",
#   "kimai_url": "https://ihre-kimai-instanz.de"
# }
```

### Option 2: Docker (Ohne Compose)

```bash
# Image bauen
docker build -t kimai-mcp-server .

# Server starten
docker run -d \
  --name kimai-mcp-server \
  -p 8000:8000 \
  -e KIMAI_URL=https://ihre-kimai-instanz.de \
  -e KIMAI_API_TOKEN=ihr-token \
  -e MCP_SERVER_TOKEN=ihr-server-token \
  kimai-mcp-server

# Token aus Logs holen (wenn automatisch generiert)
docker logs kimai-mcp-server | grep "Generated new authentication token"
```

### Option 3: Direkte Installation (Entwicklung/Test)

```bash
# Repository klonen
git clone https://github.com/glazperle/kimai_mcp.git
cd kimai_mcp

# Mit Server-Dependencies installieren
pip install -e ".[server]"

# Umgebungsvariablen setzen
export KIMAI_URL=https://ihre-kimai-instanz.de
export KIMAI_API_TOKEN=ihr-token
export MCP_SERVER_TOKEN=ihr-server-token  # optional

# Server starten
kimai-mcp-server --host 0.0.0.0 --port 8000
```

## Client-Konfiguration

Nachdem der Server läuft, konfigurieren Sie die Clients:

### Claude Desktop Konfiguration

**Datei:** `claude_desktop_config.json`

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**Linux:** `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "kimai": {
      "url": "http://ihre-server-adresse:8000/sse",
      "headers": {
        "Authorization": "Bearer ihr-mcp-server-token"
      }
    }
  }
}
```

**Wichtig:**
- Ersetzen Sie `ihre-server-adresse` mit der IP/Domain Ihres Servers
- Ersetzen Sie `ihr-mcp-server-token` mit dem Token aus den Server-Logs
- Für interne Netzwerke: verwenden Sie die interne IP (z.B. `http://192.168.1.100:8000/sse`)
- Für Produktion: verwenden Sie HTTPS mit Reverse Proxy (siehe unten)

### Andere MCP-Clients

Die Konfiguration ist für andere MCP-Clients ähnlich. Sie benötigen:
- **URL:** `http://ihre-server-adresse:8000/sse`
- **Authentication Header:** `Authorization: Bearer ihr-mcp-server-token`

## Produktions-Deployment mit HTTPS

Für Produktionsumgebungen sollten Sie HTTPS verwenden.

### Mit Reverse Proxy (Nginx)

```nginx
# /etc/nginx/sites-available/kimai-mcp

upstream kimai_mcp {
    server 127.0.0.1:8000;
}

server {
    listen 443 ssl http2;
    server_name mcp.ihre-domain.de;

    ssl_certificate /etc/ssl/certs/ihre-domain.crt;
    ssl_certificate_key /etc/ssl/private/ihre-domain.key;

    location / {
        proxy_pass http://kimai_mcp;
        proxy_http_version 1.1;

        # SSE-spezifische Headers
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;

        # Standard Proxy Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Client-Konfiguration mit HTTPS:

```json
{
  "mcpServers": {
    "kimai": {
      "url": "https://mcp.ihre-domain.de/sse",
      "headers": {
        "Authorization": "Bearer ihr-mcp-server-token"
      }
    }
  }
}
```

### Mit Traefik (Docker)

```yaml
# docker-compose.yml erweitern

version: '3.8'

services:
  kimai-mcp-server:
    # ... bestehende Konfiguration ...

    networks:
      - traefik

    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.kimai-mcp.rule=Host(`mcp.ihre-domain.de`)"
      - "traefik.http.routers.kimai-mcp.entrypoints=websecure"
      - "traefik.http.routers.kimai-mcp.tls.certresolver=letsencrypt"
      - "traefik.http.services.kimai-mcp.loadbalancer.server.port=8000"

networks:
  traefik:
    external: true
```

## Sicherheit

### 1. Token-Sicherheit

**Wichtig:** Das `MCP_SERVER_TOKEN` ist wie ein Passwort zu behandeln!

```bash
# Sicheren Token generieren (Linux/macOS)
openssl rand -base64 32

# Oder mit Python
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

- ✅ Token sicher speichern (z.B. in Secrets Management)
- ✅ Token regelmäßig rotieren
- ✅ Unterschiedliche Token für verschiedene Umgebungen (Dev/Staging/Prod)
- ❌ Token niemals in Git committen

### 2. Netzwerk-Sicherheit

- ✅ Server nur im internen Netzwerk betreiben
- ✅ Firewall-Regeln: Nur notwendige Ports öffnen
- ✅ HTTPS in Produktion verwenden
- ✅ Reverse Proxy mit Rate Limiting
- ❌ Server nicht direkt im Internet exponieren (ohne zusätzliche Sicherheit)

### 3. SSL/TLS für Kimai-Verbindung

Wenn Ihre Kimai-Instanz selbst-signierte Zertifikate verwendet:

```yaml
# docker-compose.yml
services:
  kimai-mcp-server:
    environment:
      - KIMAI_SSL_VERIFY=/app/certs/ca-bundle.crt
    volumes:
      - ./certs/ca-bundle.crt:/app/certs/ca-bundle.crt:ro
```

## Monitoring & Wartung

### Health Check

```bash
# Health Check
curl http://localhost:8000/health

# Mit JSON formatierung
curl -s http://localhost:8000/health | jq
```

### Logs ansehen

```bash
# Docker Compose
docker-compose logs -f

# Nur die letzten 100 Zeilen
docker-compose logs --tail=100

# Docker (ohne Compose)
docker logs -f kimai-mcp-server
```

### Server neu starten

```bash
# Docker Compose
docker-compose restart

# Docker
docker restart kimai-mcp-server
```

### Updates durchführen

```bash
# Repository aktualisieren
git pull origin main

# Container neu bauen und starten
docker-compose down
docker-compose build
docker-compose up -d
```

## Troubleshooting

### Problem: "Connection refused"

```bash
# 1. Prüfen ob Container läuft
docker-compose ps

# 2. Logs prüfen
docker-compose logs

# 3. Port-Binding prüfen
docker-compose port kimai-mcp-server 8000
```

### Problem: "401 Unauthorized"

- ✅ Token korrekt in Client-Konfiguration?
- ✅ Token-Format: `Authorization: Bearer IHR_TOKEN`
- ✅ Token aus Server-Logs kopieren (wenn automatisch generiert)

### Problem: "SSL verification failed" (Kimai-Verbindung)

```bash
# Option 1: CA-Zertifikat verwenden
docker-compose exec kimai-mcp-server \
  printenv KIMAI_SSL_VERIFY

# Option 2: SSL-Verifikation deaktivieren (nur für Test!)
# In .env:
# KIMAI_SSL_VERIFY=false
```

### Problem: Server startet nicht

```bash
# Detaillierte Logs
docker-compose logs --tail=200

# Container-Status
docker-compose ps

# Umgebungsvariablen prüfen
docker-compose config
```

## Beispiel-Szenarien

### Szenario 1: Kleine Firma (5-10 Benutzer)

```bash
# Einfaches Setup auf einem internen Server
cd /opt/kimai-mcp
docker-compose up -d

# Clients verbinden sich über interne IP
# http://192.168.1.100:8000/sse
```

### Szenario 2: Mittleres Unternehmen (mit SSL)

```bash
# Setup mit Nginx Reverse Proxy und Let's Encrypt
# Server: https://mcp.firma.de/sse
# Automatische SSL-Zertifikate
# Rate Limiting und Monitoring
```

### Szenario 3: Multi-Tenant (mehrere Kimai-Instanzen)

```bash
# Mehrere Server-Instanzen auf verschiedenen Ports
docker-compose -f docker-compose.team-a.yml up -d  # Port 8001
docker-compose -f docker-compose.team-b.yml up -d  # Port 8002
```

## Performance-Optimierung

### Resource Limits anpassen

```yaml
# docker-compose.yml
services:
  kimai-mcp-server:
    deploy:
      resources:
        limits:
          cpus: '2'        # Mehr CPUs für mehr Clients
          memory: 1024M    # Mehr RAM wenn nötig
        reservations:
          cpus: '0.5'
          memory: 256M
```

### Connection Pooling

Der Server verwendet automatisch Connection Pooling für Kimai-API-Anfragen.

## Support

- **Issues:** https://github.com/glazperle/kimai_mcp/issues
- **Dokumentation:** https://github.com/glazperle/kimai_mcp
- **Kimai-Spezifisch:** https://www.kimai.org/

## Nächste Schritte

1. ✅ Server deployen (Docker Compose empfohlen)
2. ✅ Token sicher speichern
3. ✅ Clients konfigurieren
4. ✅ Health Check durchführen
5. ✅ In Produktion: HTTPS konfigurieren
6. ✅ Monitoring einrichten
7. ✅ Backup-Strategie planen

Viel Erfolg mit Ihrem zentralen Kimai MCP Server! 🚀
