<?php

declare(strict_types=1);

script('nc_ai_bridge', 'nc_ai_bridge');

/** @var array $_ */
/** @var \OCP\IL10N $l */
?>
<div id="nc-ai-bridge"
     data-fastapi-base-url="<?= p($_['fastapiBaseUrl']) ?>"
     data-bootstrap-url="<?= p($_['bootstrapUrl']) ?>"
     data-sso-consume-url="<?= p($_['ssoConsumeUrl']) ?>">
    <div style="padding: 20px; max-width: 720px;">
        <h2><?= $l->t('Connecting to AI Workspace…') ?></h2>
        <p><?= $l->t('Your Nextcloud session is being exchanged for a short-lived handoff token.') ?></p>
        <p id="nc-ai-bridge-status"><?= $l->t('Preparing secure sign-in…') ?></p>
        <noscript>
            <p><?= $l->t('JavaScript is required for the bridge to launch.') ?></p>
        </noscript>
    </div>
</div>
