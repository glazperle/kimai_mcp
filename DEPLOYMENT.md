# Kimai MCP Server - Zentrales Deployment

Dieses Dokument beschreibt, wie Sie den Kimai MCP Server zentral in Ihrem Unternehmen bereitstellen können, sodass Sie ihn nicht auf jedem Client lokal installieren müssen.

## 📊 Server-Typen

| Server | Befehl | Protokoll | Anwendung |
|--------|--------|-----------|-----------|
| **Streamable HTTP** | `kimai-mcp-streamable` | HTTP Streamable + OAuth 2.1 | Claude.ai Connectors (Web/Mobile), Teams |
| **Lokaler Server** | `kimai-mcp` | MCP Stdio | Claude Desktop (Lokal) |
| **SSE Server** | `kimai-mcp-server` | HTTP/SSE | **Deprecated — nicht verwenden** |

> **Deprecation-Hinweis:** Der SSE-Server (`kimai-mcp-server`) ist deprecated und **nicht funktionsfähig** (der SSE-Transport wurde aus der MCP-Spezifikation entfernt). Er gibt beim Start eine entsprechende Warnung aus. Verwenden Sie stattdessen den Streamable-HTTP-Server (`kimai-mcp-streamable`).

### Streamable HTTP Server

Der Streamable HTTP Server ist optimiert für **Claude.ai Connectors**:

- Funktioniert mit Claude.ai Web und Mobile Apps
- **OAuth 2.1** mit Dynamic Client Registration und PKCE (seit v2.12.0): ein zentraler, geschützter Endpoint `/mcp`
- Kimai-Credentials werden serverseitig in `users.json` konfiguriert
- Kein Kimai-Token im Client erforderlich

## 🔐 Authentifizierung

Es gibt zwei Authentifizierungsmodi:

| Modus | Endpoint | Status |
|-------|----------|--------|
| **OAuth 2.1** (empfohlen) | `/mcp` | Aktuell |
| **Legacy-Slugs** | `/mcp/{user_slug}` | Deprecated |

### OAuth 2.1 (empfohlen, seit v2.12.0)

- Clients (z.B. Claude.ai) registrieren sich automatisch per **Dynamic Client Registration**
- **PKCE (S256)** ist verpflichtend
- Benutzer melden sich auf einer Login-Seite (`/oauth/login`) mit ihrem **User-Slug** und einem persönlichen **`auth_secret`** an
- Access-Tokens sind **1 Stunde** gültig; Refresh-Tokens bis zu **30 Tage** (Refresh erfolgt automatisch durch den Client)
- Tokens werden **in-memory** gehalten: Nach einem Server-Neustart müssen sich Benutzer neu verbinden
- Registrierte OAuth-Clients können optional in einer Datei persistiert werden (`--oauth-state-file`), damit nach einem Neustart keine Neuregistrierung des Connectors nötig ist

### Legacy-Slugs (deprecated)

Die früheren per-User-Endpoints `/mcp/{slug}` funktionieren weiterhin, sind aber deprecated:

- Jeder, der den Slug errät, erhält **vollen Zugriff** auf das zugehörige Kimai-Konto
- Der Server warnt beim Start vor Slugs mit niedriger Entropie (kürzer als 16 Zeichen oder reine Kleinbuchstaben-Wörter)
- Empfehlung: `auth_secret` pro User setzen, auf OAuth umstellen und die Legacy-Endpoints mit `--disable-legacy-slugs` abschalten

## 🚀 Setup

### 1. users.json erstellen

```bash
# Repository klonen
git clone https://github.com/glazperle/kimai_mcp.git
cd kimai_mcp

# Zufälligen Slug pro User generieren (WICHTIG für Sicherheit!)
python -c "import secrets; print(secrets.token_urlsafe(16))"
# Beispiel-Ausgabe: xK9mP2qW7vL4aB8c

# auth_secret pro User generieren (für OAuth-Login)
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Users-Konfiguration erstellen
cp config/users.example.json config/users.json
nano config/users.json
```

**config/users.json** Format:

```json
{
  "xK9mP2qW7vL4aB8c": {
    "kimai_url": "https://kimai.firma.de",
    "kimai_token": "api-token-fuer-benutzer-1",
    "auth_secret": "langes-zufaelliges-oauth-login-secret-1"
  },
  "bN3hT8rY5jF6cD2e": {
    "kimai_url": "https://kimai.firma.de",
    "kimai_token": "api-token-fuer-benutzer-2",
    "auth_secret": "langes-zufaelliges-oauth-login-secret-2"
  }
}
```

**Felder pro User:**

| Feld | Erforderlich | Beschreibung |
|------|--------------|--------------|
| `kimai_url` | ✅ Ja | Kimai-Server-URL (muss mit `http://` oder `https://` beginnen) |
| `kimai_token` | ✅ Ja | Kimai API-Token des Benutzers |
| `auth_secret` | Für OAuth | Persönliches Secret für den OAuth-Login. Ohne `auth_secret` kann sich der User nicht per OAuth anmelden. Alternativ per Umgebungsvariable `KIMAI_USER_<SLUG>_AUTH_SECRET` setzbar (überschreibt den Wert aus der Datei) |
| `ssl_verify` | ❌ Optional | `true` (Standard), `false` oder Pfad zu einem CA-Zertifikat |

**Hinweise:**

- Slugs dürfen nur Buchstaben, Ziffern, `-` und `_` enthalten (`^[a-zA-Z0-9_-]+$`)
- Schlüssel mit führendem `_` (z.B. `"_SECURITY_WARNING"`) werden als Kommentare ignoriert
- Das frühere Feld `kimai_user_id` wurde entfernt; alte Dateien laden weiterhin, das Feld wird ignoriert
- Statt einer Datei kann die Konfiguration auch über Umgebungsvariablen erfolgen: `USERS_CONFIG` (JSON) oder `KIMAI_USER_<SLUG>_URL` / `_TOKEN` / `_SSL_VERIFY` / `_AUTH_SECRET`

### 2. Server starten

**Produktiv (hinter HTTPS-Reverse-Proxy, mit OAuth):**

```bash
pip install -e ".[server]"

kimai-mcp-streamable \
  --users-config ./config/users.json \
  --public-url https://mcp.firma.de \
  --trusted-proxy 127.0.0.1 \
  --oauth-state-file ./config/oauth_clients.json \
  --disable-legacy-slugs
```

**Mit Docker Compose:**

```bash
docker-compose up -d
docker-compose logs -f
```

> **Hinweis:** Für OAuth hinter einem Reverse Proxy müssen im Container die Umgebungsvariablen `KIMAI_MCP_PUBLIC_URL`, `KIMAI_MCP_TRUSTED_PROXIES` und ggf. `KIMAI_MCP_DISABLE_LEGACY_SLUGS` / `KIMAI_MCP_OAUTH_STATE_FILE` gesetzt werden (z.B. im `environment:`-Block der `docker-compose.yml`).

### CLI-Optionen / Umgebungsvariablen

| Option | Umgebungsvariable | Beschreibung |
|--------|-------------------|--------------|
| `--host` | — | Bind-Adresse (Standard: `0.0.0.0`) |
| `--port` | — | Port (Standard: `8000`) |
| `--users-config FILE` | `USERS_CONFIG_FILE` | Pfad zur `users.json` |
| `--public-url URL` | `KIMAI_MCP_PUBLIC_URL` | Öffentliche Basis-URL; wird als OAuth-Issuer und Resource-URL verwendet. **Hinter einem Reverse Proxy zwingend erforderlich.** Standard: `http://localhost:{port}` |
| `--oauth-state-file FILE` | `KIMAI_MCP_OAUTH_STATE_FILE` | JSON-Datei zur Persistierung registrierter OAuth-Clients über Neustarts hinweg |
| `--disable-legacy-slugs` | `KIMAI_MCP_DISABLE_LEGACY_SLUGS` | Deaktiviert die deprecated `/mcp/{slug}`-Endpoints |
| `--trusted-proxy IP` | `KIMAI_MCP_TRUSTED_PROXIES` (kommasepariert) | IP eines vertrauenswürdigen Reverse Proxy, dessen `X-Forwarded-For`/`X-Real-IP`-Header akzeptiert werden; mehrfach angebbar. Ohne diese Option werden Proxy-Header ignoriert |
| `--rate-limit-rpm N` | `RATE_LIMIT_RPM` | Max. Requests pro Minute pro IP (Standard: 60, 0 = deaktiviert) |
| `--version` | — | Version anzeigen |

### 3. In Claude.ai hinzufügen (OAuth)

1. Claude.ai öffnen: **Settings → Connectors → Add custom connector**
2. URL eingeben: `https://mcp.firma.de/mcp` (**ohne** Slug)
3. Claude.ai registriert sich automatisch per Dynamic Client Registration
4. Beim Verbinden erscheint die Login-Seite: **User-Slug** und **auth_secret** eingeben
5. Fertig! Das Token wird automatisch erneuert (bis 30 Tage); nach einem Server-Neustart ist eine erneute Verbindung nötig

### Endpoints

| Endpoint | Methode | Beschreibung |
|----------|---------|--------------|
| `/` | GET | Server-Info (Name, Version, Endpoints) |
| `/health` | GET | Health Check (gibt nur User-Anzahl zurück, keine Slugs) |
| `/mcp` | GET/POST/DELETE | OAuth-geschützter MCP-Endpoint (Bearer-Token) |
| `/mcp/{slug}` | GET/POST/DELETE | Legacy-MCP-Endpoint pro User (**deprecated**, abschaltbar) |
| `/oauth/login` | GET/POST | HTML-Login-Formular (User-Slug + auth_secret) |
| `/authorize`, `/token`, `/register`, `/revoke` | — | OAuth 2.1 Authorization-Server-Endpoints |
| `/.well-known/oauth-authorization-server` | GET | OAuth-Metadaten (RFC 8414) |
| `/.well-known/oauth-protected-resource/mcp` | GET | Protected-Resource-Metadaten (RFC 9728) |

## 🔒 Sicherheit

### Integrierte Sicherheitsfunktionen

| Feature | Beschreibung | Konfiguration |
|---------|--------------|---------------|
| **OAuth 2.1** | DCR, PKCE-Pflicht, Tokens mit kurzer Laufzeit | `auth_secret` pro User |
| **Rate Limiting** | Begrenzt Anfragen pro IP | `--rate-limit-rpm=60` (Standard: 60/min) |
| **Security Headers** | X-Content-Type-Options, X-Frame-Options, etc. | Automatisch aktiviert |
| **Enumeration-Schutz** | Zufällige Verzögerung bei 404, Blockierung nach zu vielen Fehlversuchen | Automatisch |
| **Proxy-Header-Schutz** | `X-Forwarded-For`/`X-Real-IP` werden nur von vertrauenswürdigen Proxys akzeptiert | `--trusted-proxy` |
| **Slug-Warnung** | Startup-Warnung bei Legacy-Slugs mit niedriger Entropie | Automatisch |
| **Constant-Time-Vergleich** | `auth_secret`-Prüfung ohne Timing-Leck | Automatisch |

### Token- und Secret-Verwaltung

```bash
# Sichere Secrets generieren
python -c "import secrets; print(secrets.token_urlsafe(16))"   # User-Slug
python -c "import secrets; print(secrets.token_urlsafe(32))"   # auth_secret
```

- **Kimai API-Token**: pro User in `users.json`; bestimmt die Kimai-Berechtigungen des Users
- **auth_secret**: pro User; nur für den OAuth-Login. Sicher an den jeweiligen Benutzer kommunizieren, regelmäßig rotieren
- `users.json` restriktiv berechtigen (z.B. `chmod 600`) und nicht ins Versionskontrollsystem einchecken
- Alternativ Secrets per Umgebungsvariablen setzen (`KIMAI_USER_<SLUG>_AUTH_SECRET`), z.B. aus einem Secret-Store

### Transport-Sicherheit

- **OAuth erfordert HTTPS**: Die `--public-url` (OAuth-Issuer) muss in Produktion eine `https://`-URL sein. Claude.ai akzeptiert nur HTTPS-Connectors
- TLS-Terminierung über einen Reverse Proxy (siehe unten)
- Server selbst nur auf localhost oder im internen Netz binden, nicht direkt im Internet exponieren

### Netzwerk-Sicherheit

- ✅ Reverse Proxy mit HTTPS in Produktion
- ✅ `--trusted-proxy` auf die Proxy-IP setzen, damit Rate-Limiting und Enumeration-Schutz die echte Client-IP sehen
- ✅ Firewall-Regeln: nur den Proxy-Port öffnen
- ❌ Den MCP-Server-Port (8000) nicht direkt im Internet exponieren

## 🌐 Produktions-Deployment mit HTTPS

### Mit Nginx Reverse Proxy

```nginx
# /etc/nginx/sites-available/kimai-mcp

upstream kimai_mcp {
    server 127.0.0.1:8000;
}

server {
    listen 443 ssl http2;
    server_name mcp.firma.de;

    ssl_certificate /etc/ssl/certs/firma.crt;
    ssl_certificate_key /etc/ssl/private/firma.key;

    location / {
        proxy_pass http://kimai_mcp;
        proxy_http_version 1.1;

        # Streaming-Antworten (SSE innerhalb des Streamable-HTTP-Transports)
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;

        # Standard Proxy Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Dazu passend den Server starten mit:

```bash
kimai-mcp-streamable \
  --users-config ./config/users.json \
  --public-url https://mcp.firma.de \
  --trusted-proxy 127.0.0.1 \
  --oauth-state-file ./config/oauth_clients.json \
  --disable-legacy-slugs
```

> **Wichtig:**
> - `--public-url` muss exakt der öffentlichen HTTPS-URL entsprechen, sonst schlagen OAuth-Discovery und Token-Validierung fehl.
> - `--trusted-proxy` muss die IP enthalten, von der aus der Proxy den MCP-Server erreicht (hier `127.0.0.1`). Ohne diese Angabe werden `X-Forwarded-For`-Header ignoriert und alle Requests scheinen vom Proxy zu kommen — das Rate-Limit würde dann alle Benutzer gemeinsam treffen.

## 📊 Monitoring & Wartung

### Health Check

```bash
curl -s https://mcp.firma.de/health | jq

# Beispiel-Antwort:
# {
#   "status": "healthy",
#   "version": "2.12.0",
#   "transport": "streamable-http",
#   "user_count": 3
# }
# Hinweis: User-Slugs werden aus Sicherheitsgründen nicht angezeigt
```

### Logs ansehen

```bash
# Docker Compose
docker-compose logs -f
docker-compose logs --tail=100 -f

# Wichtige Log-Ereignisse:
# - "User '<slug>' connected to Kimai ..."         (Session-Initialisierung)
# - "OAuth login successful for user '<slug>'"     (erfolgreicher OAuth-Login)
# - "Failed OAuth login attempt for user slug ..." (fehlgeschlagener Login)
# - "User slug '...' has low entropy ..."          (Warnung: unsicherer Legacy-Slug)
```

## 🔧 Troubleshooting

### Problem: Claude.ai kann den Connector nicht hinzufügen

**Mögliche Ursachen:**

1. `--public-url` fehlt oder stimmt nicht mit der öffentlichen HTTPS-URL überein
2. Server ist nicht über HTTPS erreichbar (Claude.ai erfordert HTTPS)
3. Reverse Proxy leitet die OAuth-Endpoints (`/.well-known/...`, `/authorize`, `/token`, `/register`) nicht weiter

**Debug:**

```bash
# OAuth-Metadaten müssen erreichbar sein und die korrekte issuer-URL enthalten
curl -s https://mcp.firma.de/.well-known/oauth-authorization-server | jq
```

### Problem: Login-Seite meldet "OAuth login is not enabled for user"

**Ursache:** Für den User ist kein `auth_secret` konfiguriert.

**Lösung:** `auth_secret` in `users.json` setzen (oder `KIMAI_USER_<SLUG>_AUTH_SECRET`) und den Server neu starten.

### Problem: Verbindung bricht nach Server-Neustart ab

**Ursache:** Access- und Refresh-Tokens werden in-memory gehalten und gehen beim Neustart verloren.

**Lösung:** In Claude.ai den Connector neu verbinden (erneuter Login). Mit `--oauth-state-file` bleibt zumindest die Client-Registrierung erhalten, sodass keine Neuanlage des Connectors nötig ist.

### Problem: "No active session for the authenticated user" (403)

**Ursache:** Die Kimai-Session des Users konnte beim Serverstart nicht initialisiert werden (z.B. ungültiger Kimai-Token oder Kimai nicht erreichbar).

**Debug:**

```bash
# Kimai-Verbindung direkt testen
curl -H "X-AUTH-TOKEN: ihr-kimai-token" https://kimai.firma.de/api/version

# Server-Logs auf "Failed to initialize user '<slug>'" prüfen
docker-compose logs | grep "Failed to"
```

### Problem: Kimai API Error (Status: 403) in Tool-Antworten

**Ursache:** Der Kimai API-Token des Users hat nicht die nötigen Berechtigungen. Kimai 2.57/2.58 haben die API-Berechtigungen verschärft.

**Lösung:** Rollen/Team-Berechtigungen des Users in Kimai prüfen. Die Fehlermeldung des MCP-Servers enthält Statuscode und Details der API-Antwort.

### Problem: SSL-Zertifikatfehler zur Kimai-Instanz

**Für selbst-signierte Zertifikate:**

```json
{
  "xK9mP2qW7vL4aB8c": {
    "kimai_url": "https://kimai.firma.de",
    "kimai_token": "...",
    "auth_secret": "...",
    "ssl_verify": "/app/certs/ca-bundle.crt"
  }
}
```

```yaml
# In docker-compose.yml volumes einkommentieren:
volumes:
  - ./certs/ca-bundle.crt:/app/certs/ca-bundle.crt:ro
```

## 📈 Performance & Skalierung

- Die Standard-Konfiguration unterstützt problemlos kleine bis mittlere Teams; pro User wird eine eigene Kimai-Client-Session gehalten
- Operationen mit `user_scope="all"` (z.B. Anwesenheits-Reports) laufen parallelisiert
- Resource-Limits können in `docker-compose.yml` angepasst werden:

```yaml
deploy:
  resources:
    limits:
      cpus: '4'
      memory: 2G
```

> **Hinweis zu Load Balancing:** OAuth-Tokens und MCP-Sessions werden in-memory pro Instanz gehalten. Mehrere Instanzen hinter einem Load Balancer erfordern Sticky Sessions; für die meisten Teams ist eine einzelne Instanz ausreichend.

## 💡 Zusammenfassung

**Server-Setup (einmalig):**
1. ✅ `users.json` mit zufälligen Slugs, Kimai-Tokens und `auth_secret` pro User erstellen
2. ✅ Server hinter HTTPS-Reverse-Proxy starten (`--public-url`, `--trusted-proxy`, `--oauth-state-file`, `--disable-legacy-slugs`)
3. ✅ Health Check prüfen

**Client-Setup (pro Nutzer):**
1. ✅ In Claude.ai: Custom Connector mit URL `https://mcp.firma.de/mcp` hinzufügen
2. ✅ Beim Verbinden mit User-Slug und `auth_secret` anmelden
3. ✅ Fertig — Token-Refresh erfolgt automatisch

**Vorteile:**
- ✅ Installation nur einmal auf dem Server
- ✅ OAuth 2.1 statt geheimer URLs
- ✅ Jeder Nutzer behält seine individuellen Kimai-Berechtigungen
- ✅ Audit-Trail pro Nutzer
- ✅ Zentrale Updates

## 📞 Support

- **Issues:** https://github.com/glazperle/kimai_mcp/issues
- **Dokumentation:** https://github.com/glazperle/kimai_mcp
- **Kimai-Spezifisch:** https://www.kimai.org/
