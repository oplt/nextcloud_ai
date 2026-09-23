<?php

declare(strict_types=1);

namespace OCA\NcAiBridge\Controller;

use OCA\NcAiBridge\AppInfo\Application;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http\Attribute\NoAdminRequired;
use OCP\AppFramework\Http\JSONResponse;
use OCP\IConfig;
use OCP\IGroupManager;
use OCP\IRequest;
use OCP\IUser;
use OCP\IUserSession;
use OCP\IURLGenerator;

class AuthController extends Controller {
    public function __construct(
        IRequest $request,
        private IUserSession $userSession,
        private IGroupManager $groupManager,
        private IConfig $config,
        private IURLGenerator $urlGenerator,
    ) {
        parent::__construct(Application::APP_ID, $request);
    }

    #[NoAdminRequired]
    public function bootstrap(): JSONResponse {
        $user = $this->userSession->getUser();
        if (!$user instanceof IUser) {
            return new JSONResponse(['message' => 'Unauthenticated'], 401);
        }

        $sharedSecret = $this->config->getAppValue(Application::APP_ID, 'bridge_shared_secret', '');
        $issuer = $this->config->getAppValue(Application::APP_ID, 'bridge_issuer', 'nextcloud-bridge');
        $audience = $this->config->getAppValue(Application::APP_ID, 'bridge_audience', 'fastapi-nextcloud');
        $ttlSeconds = (int) $this->config->getAppValue(Application::APP_ID, 'bridge_ttl_seconds', '60');
        $baseUrl = $this->resolveNextcloudBaseUrl();

        if ($sharedSecret === '') {
            return new JSONResponse(['message' => 'bridge_shared_secret is not configured'], 500);
        }
        if ($baseUrl === '') {
            return new JSONResponse(['message' => 'Could not determine Nextcloud base URL'], 500);
        }

        $now = time();
        $payload = [
            'iss' => $issuer,
            'aud' => $audience,
            'sub' => $user->getUID(),
            'preferred_username' => $user->getUID(),
            'display_name' => $user->getDisplayName(),
            'email' => method_exists($user, 'getEMailAddress') ? $user->getEMailAddress() : null,
            'groups' => $this->groupManager->getUserGroupIds($user),
            'provider' => 'nextcloud',
            'nc_base_url' => $baseUrl,
            'jti' => bin2hex(random_bytes(16)),
            'iat' => $now,
            'nbf' => $now,
            'exp' => $now + max(15, min(300, $ttlSeconds)),
        ];

        return new JSONResponse([
            'bridge_token' => $this->encodeJwt($payload, $sharedSecret),
            'expires_in' => $payload['exp'] - $payload['iat'],
            'principal' => [
                'sub' => $payload['sub'],
                'username' => $payload['preferred_username'],
                'display_name' => $payload['display_name'],
                'email' => $payload['email'],
                'groups' => $payload['groups'],
                'nc_base_url' => $payload['nc_base_url'],
            ],
        ]);
    }

    private function resolveNextcloudBaseUrl(): string {
        $overwriteCliUrl = rtrim($this->config->getSystemValueString('overwrite.cli.url', ''), '/');
        if ($overwriteCliUrl !== '') {
            return $overwriteCliUrl;
        }
        // IURLGenerator uses Nextcloud's canonical/trusted proxy configuration.
        // Never derive the ACL namespace directly from client-supplied Host headers.
        return rtrim($this->urlGenerator->getAbsoluteURL('/'), '/');
    }

    private function encodeJwt(array $payload, string $secret): string {
        $header = ['alg' => 'HS256', 'typ' => 'JWT'];
        $segments = [
            $this->base64UrlEncode(json_encode($header, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)),
            $this->base64UrlEncode(json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)),
        ];
        $signingInput = implode('.', $segments);
        $signature = hash_hmac('sha256', $signingInput, $secret, true);
        $segments[] = $this->base64UrlEncode($signature);
        return implode('.', $segments);
    }

    private function base64UrlEncode(string $value): string {
        return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
    }
}
