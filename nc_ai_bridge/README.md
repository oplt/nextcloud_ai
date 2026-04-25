# nc_ai_bridge

Thin Nextcloud bridge app for an external FastAPI AI service.

## Install into Nextcloud

Copy `nc_ai_bridge/` into your Nextcloud `custom_apps/` directory and enable it:

```bash
sudo -u www-data php occ app:enable nc_ai_bridge
```

If you develop the API with **uvicorn on the host** (not Docker), Nextcloud still loads `custom_apps/nc_ai_bridge` from its own filesystem. After pulling bridge fixes (e.g. the `/workspace` route), refresh the app on the server:

```bash
# from repo root; NEXTCLOUD_HTML_ROOT must contain custom_apps/
NEXTCLOUD_HTML_ROOT=/var/www/html bash scripts/sync-nc-ai-bridge-to-nextcloud.sh
sudo -u www-data php occ app:disable nc_ai_bridge && sudo -u www-data php occ app:enable nc_ai_bridge
```

Or: `make local-sync-nc-bridge` with the same `NEXTCLOUD_HTML_ROOT` set.

## Configure app values

```bash
sudo -u www-data php occ config:app:set nc_ai_bridge fastapi_base_url --value="https://ai.example.com"
sudo -u www-data php occ config:app:set nc_ai_bridge bridge_shared_secret --value="same-secret-as-NEXTCLOUD_BRIDGE_SHARED_SECRET"
sudo -u www-data php occ config:app:set nc_ai_bridge bridge_issuer --value="nextcloud-bridge"
sudo -u www-data php occ config:app:set nc_ai_bridge bridge_audience --value="fastapi-nextcloud"
sudo -u www-data php occ config:app:set nc_ai_bridge bridge_ttl_seconds --value="60"
```

Make sure your main `config/config.php` has an accurate canonical base URL:

```php
'overwrite.cli.url' => 'https://cloud.example.com',
```

If the **AI Workspace** icon opens `http://localhost:8081/` (or another host) while you actually use Nextcloud on **:8080**, Docker/env set `OVERWRITEHOST` / `overwrite.cli.url` to the wrong port. Fix with `occ` (paths vary by install):

```bash
sudo -u www-data php occ config:system:get overwritehost
sudo -u www-data php occ config:system:delete overwritehost
sudo -u www-data php occ config:system:delete overwrite.cli.url
# Then set to the URL you use in the browser, e.g.:
sudo -u www-data php occ config:system:set overwrite.cli.url --value="http://localhost:8080"
```

The bridge script also rewrites the app-menu link to match your **current** browser origin when it can detect the bridge icon.

## Result

The app adds an **AI Workspace** navigation entry. Opening it performs a same-origin bootstrap call to Nextcloud, gets a short-lived signed bridge token, and posts that token to the FastAPI SSO consume endpoint.
