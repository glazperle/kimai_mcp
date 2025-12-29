# Kimai MCP Server - Zentrales Deployment

Dieses Dokument beschreibt, wie Sie den Kimai MCP Server zentral in Ihrem Unternehmen bereitstellen können, sodass Sie ihn nicht auf jedem Client lokal installieren müssen.

## 🔐 Per-Client Authentifizierung

**WICHTIG:** Dieser Server verwendet **per-client Authentifizierung**. Jeder Benutzer verwendet seinen **eigenen Kimai API-Token**.

### Warum per-client Authentication?

- ✅ **Individuelle Berechtigungen**: Jeder Nutzer hat nur Zugriff auf seine eigenen Daten
- ✅ **Auditing**: Alle Aktionen sind eindeutig einem Benutzer zuordenbar
- ✅ **Compliance**: Keine gemeinsamen Credentials
- ✅ **Sicherheit**: Keine zentral gespeicherten Kimai-Credentials
- ✅ **Flexibilität**: Nutzer können verschiedene Kimai-Instanzen verwenden

### Wie funktioniert es?

1. **Server**: Stellt nur die MCP-Protokoll-Infrastruktur bereit
2. **Clients**: Jeder Client sendet seinen eigenen Kimai API-Token
3. **Sessions**: Server erstellt isolierte Sessions pro Client
4. **Keine Speicherung**: Server speichert keine Kimai-Credentials

## 🚀 Deployment-Optionen

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

Minimale Konfiguration in `.env`:

```bash
# OPTIONAL: MCP Server Token (wird automatisch generiert wenn nicht gesetzt)
# MCP_SERVER_TOKEN=ihr-sicherer-token

# OPTIONAL: Default Kimai URL (Clients können diese überschreiben)
# DEFAULT_KIMAI_URL=https://ihre-kimai-instanz.de

# OPTIONAL: SSL Verification
# KIMAI_SSL_VERIFY=true
```

**Hinweis:** Im Gegensatz zur Vorgängerversion benötigen Sie **KEINE** Kimai API-Credentials mehr in der Server-Konfiguration!

#### 3. Server starten

```bash
# Server im Hintergrund starten
docker-compose up -d

# Logs ansehen
docker-compose logs -f

# MCP Server Token finden (wenn automatisch generiert)
docker-compose logs | grep "Generated new authentication token"
```

Beispiel-Output:
```
======================================================================
Generated new authentication token for MCP server:
  AbCdEf123456789_YourGeneratedToken_XyZ
======================================================================
IMPORTANT: Save this token securely!
Clients will need this token to connect to the server.
======================================================================
Remote MCP server starting on http://0.0.0.0:8000
Per-client Kimai authentication enabled
```

#### 4. Server testen

```bash
# Health Check
curl http://localhost:8000/health

# Erwartete Antwort:
# {
#   "status": "healthy",
#   "version": "2.6.0",
#   "mode": "per-client-auth",
#   "default_kimai_url": "https://ihre-kimai-instanz.de",
#   "active_sessions": 0
# }
```

### Option 2: Docker (Ohne Compose)

```bash
# Image bauen
docker build -t kimai-mcp-server .

# Server starten (nur mit Server-Token)
docker run -d \
  --name kimai-mcp-server \
  -p 8000:8000 \
  -e MCP_SERVER_TOKEN=ihr-server-token \
  -e DEFAULT_KIMAI_URL=https://ihre-kimai-instanz.de \
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

# Server starten
kimai-mcp-server \
  --host 0.0.0.0 \
  --port 8000 \
  --default-kimai-url https://ihre-kimai-instanz.de
```

## 👥 Client-Konfiguration

**WICHTIG:** Jeder Benutzer benötigt seinen eigenen Kimai API-Token!

### Schritt 1: Kimai API-Token holen

1. In Kimai anmelden
2. Benutzerprofil öffnen (eigener Username oben rechts)
3. "API" oder "API-Zugriff" Sektion öffnen
4. Neuen API-Token erstellen oder existierenden kopieren

### Schritt 2: Claude Desktop konfigurieren

**Datei:** `claude_desktop_config.json`

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**Linux:** `~/.config/Claude/claude_desktop_config.json`

#### Minimale Konfiguration:

```json
{
  "mcpServers": {
    "kimai": {
      "url": "http://ihre-server-adresse:8000/sse",
      "headers": {
        "Authorization": "Bearer ihr-mcp-server-token",
        "X-Kimai-Token": "ihr-persönlicher-kimai-api-token"
      }
    }
  }
}
```

#### Vollständige Konfiguration (mit allen Optionen):

```json
{
  "mcpServers": {
    "kimai": {
      "url": "http://ihre-server-adresse:8000/sse",
      "headers": {
        "Authorization": "Bearer ihr-mcp-server-token",
        "X-Kimai-Token": "ihr-persönlicher-kimai-api-token",
        "X-Kimai-URL": "https://ihre-kimai-instanz.de",
        "X-Kimai-User": "42"
      }
    }
  }
}
```

**Header-Erklärung:**

| Header | Erforderlich | Beschreibung |
|--------|--------------|--------------|
| `Authorization` | ✅ Ja | MCP Server Token (vom Server-Administrator) |
| `X-Kimai-Token` | ✅ Ja | **IHR** persönlicher Kimai API-Token |
| `X-Kimai-URL` | ❌ Optional | Kimai Server URL (nutzt Server-Default wenn nicht angegeben) |
| `X-Kimai-User` | ❌ Optional | Default User ID für Operationen |

**Wichtig:**
- `Authorization`: Gleicher Token für alle Nutzer (Server-Zugang)
- `X-Kimai-Token`: **Individueller** Token pro Nutzer (Ihre Kimai-Berechtigung)

### Schritt 3: Claude Desktop neustarten

Nach dem Speichern der Konfiguration Claude Desktop neu starten.

## 📊 Beispiel-Szenarien

### Szenario 1: Kleine Firma (alle nutzen gleiche Kimai-Instanz)

**Server-Konfiguration** (`.env`):
```bash
DEFAULT_KIMAI_URL=https://kimai.firma.de
MCP_SERVER_TOKEN=FirmenToken123
```

**Client-Konfiguration** (jeder Nutzer):
```json
{
  "mcpServers": {
    "kimai": {
      "url": "http://192.168.1.100:8000/sse",
      "headers": {
        "Authorization": "Bearer FirmenToken123",
        "X-Kimai-Token": "mein-persönlicher-token"
      }
    }
  }
}
```

**Vorteile:**
- Nutzer müssen keine Kimai-URL eingeben (nutzen Server-Default)
- Jeder hat seinen eigenen API-Token
- Zentrale Verwaltung der Kimai-URL

### Szenario 2: Mehrere Kimai-Instanzen (Team A und Team B)

**Server-Konfiguration** (keine Default-URL):
```bash
MCP_SERVER_TOKEN=FirmenToken123
```

**Team A Client-Konfiguration:**
```json
{
  "mcpServers": {
    "kimai": {
      "url": "http://mcp-server.firma.de:8000/sse",
      "headers": {
        "Authorization": "Bearer FirmenToken123",
        "X-Kimai-Token": "team-a-nutzer-token",
        "X-Kimai-URL": "https://kimai-team-a.firma.de"
      }
    }
  }
}
```

**Team B Client-Konfiguration:**
```json
{
  "mcpServers": {
    "kimai": {
      "url": "http://mcp-server.firma.de:8000/sse",
      "headers": {
        "Authorization": "Bearer FirmenToken123",
        "X-Kimai-Token": "team-b-nutzer-token",
        "X-Kimai-URL": "https://kimai-team-b.firma.de"
      }
    }
  }
}
```

**Vorteile:**
- Ein MCP-Server für mehrere Kimai-Instanzen
- Flexible Nutzung
- Klare Trennung zwischen Teams

## 🔒 Sicherheit

### 1. Token-Sicherheit

**MCP Server Token:**
- Wird von allen Clients benötigt
- Kontrolliert Zugang zum MCP-Server
- Sollte firmenintern geteilt werden
- Regelmäßig rotieren

**Kimai API Token (per-client):**
- ✅ Jeder Nutzer hat seinen eigenen
- ✅ Nie mit anderen teilen
- ✅ Server speichert diese NICHT
- ✅ Nutzer ist verantwortlich für seinen Token

```bash
# Sicheren Server-Token generieren
openssl rand -base64 32

# Oder mit Python
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. Transport-Sicherheit

**Entwicklung/Test:**
```
http://192.168.1.100:8000/sse  # OK für internes Netzwerk
```

**Produktion:**
```
https://mcp.ihre-domain.de/sse  # HTTPS erforderlich!
```

### 3. Netzwerk-Sicherheit

- ✅ Server nur im internen Netzwerk betreiben
- ✅ Firewall-Regeln: Nur Port 8000 (oder konfiguriert)
- ✅ Reverse Proxy mit HTTPS in Produktion
- ✅ Optional: IP-Whitelisting
- ❌ Server nicht direkt im Internet exponieren

## 🌐 Produktions-Deployment mit HTTPS

### Mit Nginx Reverse Proxy

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
        proxy_read_timeout 86400s;  # 24 hours for long-lived SSE connections

        # Standard Proxy Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Forward client headers (important for per-client auth!)
        proxy_set_header Authorization $http_authorization;
        proxy_set_header X-Kimai-Token $http_x_kimai_token;
        proxy_set_header X-Kimai-URL $http_x_kimai_url;
        proxy_set_header X-Kimai-User $http_x_kimai_user;
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
        "Authorization": "Bearer ihr-mcp-server-token",
        "X-Kimai-Token": "ihr-persönlicher-kimai-api-token"
      }
    }
  }
}
```

## 📊 Monitoring & Wartung

### Health Check

```bash
# Basic Health Check
curl http://localhost:8000/health

# Mit JSON Formatierung
curl -s http://localhost:8000/health | jq

# Beispiel-Antwort:
# {
#   "status": "healthy",
#   "version": "2.6.0",
#   "mode": "per-client-auth",
#   "default_kimai_url": "https://kimai.firma.de",
#   "active_sessions": 5
# }
```

### Logs ansehen

```bash
# Docker Compose
docker-compose logs -f

# Nur die letzten 100 Zeilen
docker-compose logs --tail=100 -f

# Nach Client-Sessions filtern
docker-compose logs | grep "Client session"

# Beispiel-Logs:
# Client session 1a2b3c4d connected to Kimai 2.0.0 at https://kimai.firma.de
# Cleaned up client session 1a2b3c4d
```

### Server-Metriken

Der Health-Endpoint zeigt aktive Sessions:

```bash
# Anzahl aktiver Sessions
curl -s http://localhost:8000/health | jq '.active_sessions'
```

## 🔧 Troubleshooting

### Problem: "Kimai API token is required"

**Ursache:** Client sendet keinen `X-Kimai-Token` Header

**Lösung:**
```json
{
  "mcpServers": {
    "kimai": {
      "url": "http://...",
      "headers": {
        "Authorization": "Bearer server-token",
        "X-Kimai-Token": "IHR-KIMAI-TOKEN-HIER"
      }
    }
  }
}
```

### Problem: "Invalid or missing MCP server authentication token"

**Ursache:** `Authorization` Header fehlt oder ist falsch

**Lösung:**
1. Server-Token aus Logs holen: `docker-compose logs | grep "Generated new"`
2. In Client-Config eintragen: `"Authorization": "Bearer IHR-SERVER-TOKEN"`

### Problem: "Failed to connect to Kimai"

**Mögliche Ursachen:**
1. Kimai-URL falsch
2. Kimai-API-Token ungültig
3. Netzwerk-Problem

**Debug:**
```bash
# Test Kimai-Verbindung direkt
curl -H "X-AUTH-TOKEN: ihr-kimai-token" https://ihre-kimai-instanz.de/api/version

# Erwartete Antwort: {"version": "2.0.0", ...}
```

### Problem: SSL-Zertifikatfehler

**Für selbst-signierte Zertifikate:**

```bash
# In .env:
KIMAI_SSL_VERIFY=/app/certs/ca-bundle.crt

# In docker-compose.yml volumes einkommentieren:
volumes:
  - ./certs/ca-bundle.crt:/app/certs/ca-bundle.crt:ro
```

## 🎯 Best Practices

### 1. Server-Token Management

```bash
# Token in Umgebungsvariable speichern
export MCP_SERVER_TOKEN="$(openssl rand -base64 32)"

# Server starten
docker-compose up -d

# Token an Team kommunizieren (sicher!)
```

### 2. Default Kimai URL setzen

Wenn alle Nutzer die gleiche Kimai-Instanz verwenden:

```bash
# In .env
DEFAULT_KIMAI_URL=https://kimai.firma.de
```

Vorteile:
- Clients müssen keine URL angeben
- Zentrale Konfiguration
- Einfacher für Endnutzer

### 3. Monitoring aktiver Sessions

```bash
# Cron-Job für Monitoring
*/5 * * * * curl -s http://localhost:8000/health | jq '.active_sessions' > /var/log/mcp-sessions.log
```

### 4. Automatische Token-Rotation

```bash
#!/bin/bash
# rotate-server-token.sh

NEW_TOKEN=$(openssl rand -base64 32)
echo "MCP_SERVER_TOKEN=$NEW_TOKEN" > .env.new

echo "Neuer Server-Token: $NEW_TOKEN"
echo "1. Update .env"
echo "2. Restart Server: docker-compose restart"
echo "3. Update alle Client-Konfigurationen"
echo "4. Alten Token nach 24h deaktivieren"
```

## 📈 Performance & Skalierung

### Resource Limits

Standard-Konfiguration unterstützt ~10-20 gleichzeitige Nutzer.

Für mehr Nutzer in `docker-compose.yml` anpassen:

```yaml
deploy:
  resources:
    limits:
      cpus: '4'
      memory: 2G
    reservations:
      cpus: '1'
      memory: 512M
```

### Load Balancing (für große Teams)

Für >50 Nutzer mehrere Server-Instanzen mit Load Balancer:

```nginx
upstream kimai_mcp_cluster {
    least_conn;
    server mcp-server-1:8000;
    server mcp-server-2:8000;
    server mcp-server-3:8000;
}

server {
    location / {
        proxy_pass http://kimai_mcp_cluster;
        # ... rest of config
    }
}
```

## 💡 Zusammenfassung

**Server-Setup (einmalig):**
1. ✅ `docker-compose up -d`
2. ✅ MCP Server Token aus Logs kopieren
3. ✅ Optional: Default Kimai URL setzen

**Client-Setup (pro Nutzer):**
1. ✅ Eigenen Kimai API-Token holen
2. ✅ Claude Desktop Config anpassen
3. ✅ MCP Server Token (vom Admin) + eigenen Kimai Token eintragen
4. ✅ Claude Desktop neu starten

**Vorteile:**
- ✅ Installation nur einmal auf dem Server
- ✅ Jeder Nutzer behält seine individuellen Berechtigungen
- ✅ Audit-Trail pro Nutzer
- ✅ Keine gemeinsamen Credentials
- ✅ Compliance-konform
- ✅ Zentrale Updates

## 📞 Support

- **Issues:** https://github.com/glazperle/kimai_mcp/issues
- **Dokumentation:** https://github.com/glazperle/kimai_mcp
- **Kimai-Spezifisch:** https://www.kimai.org/

Viel Erfolg mit Ihrem zentralen Kimai MCP Server! 🚀
