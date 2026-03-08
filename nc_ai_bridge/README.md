# nc_ai_bridge

Thin Nextcloud bridge app for an external FastAPI AI service.

## Install into Nextcloud

Copy `nc_ai_bridge/` into your Nextcloud `custom_apps/` directory and enable it:

```bash
sudo -u www-data php occ app:enable nc_ai_bridge
```

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

## Result

The app adds an **AI Workspace** navigation entry. Opening it performs a same-origin bootstrap call to Nextcloud, gets a short-lived signed bridge token, and posts that token to the FastAPI SSO consume endpoint.
