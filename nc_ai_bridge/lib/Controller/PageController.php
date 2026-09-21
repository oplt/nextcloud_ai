<?php

declare(strict_types=1);

namespace OCA\NcAiBridge\Controller;

use OCA\NcAiBridge\AppInfo\Application;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http\Attribute\NoAdminRequired;
use OCP\AppFramework\Http\Attribute\NoCSRFRequired;
use OCP\AppFramework\Http\TemplateResponse;
use OCP\IConfig;
use OCP\IRequest;
use OCP\IURLGenerator;

class PageController extends Controller {
    public function __construct(
        IRequest $request,
        private IConfig $config,
        private IURLGenerator $urlGenerator,
    ) {
        parent::__construct(Application::APP_ID, $request);
    }

    #[NoAdminRequired]
    #[NoCSRFRequired]
    public function index(): TemplateResponse {
        $fastapiBaseUrl = rtrim(
            $this->config->getAppValue(Application::APP_ID, 'fastapi_base_url', ''),
            '/'
        );

        $params = [
            'fastapiBaseUrl' => $fastapiBaseUrl,
            'bootstrapUrl' => $this->urlGenerator->linkToRoute(Application::APP_ID . '.auth.bootstrap'),
            'ssoConsumeUrl' => $fastapiBaseUrl . '/api/v1/auth/nextcloud/sso/consume',
        ];

        $response = new TemplateResponse(Application::APP_ID, 'index', $params, TemplateResponse::RENDER_AS_USER);
        if ($fastapiBaseUrl !== '') {
            $response->getContentSecurityPolicy()->addAllowedFormActionDomain($fastapiBaseUrl);
        }

        return $response;
    }
}
