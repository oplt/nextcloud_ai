<?php

declare(strict_types=1);

return [
    'routes' => [
        ['name' => 'page#index', 'url' => '/', 'verb' => 'GET'],
        ['name' => 'auth#bootstrap', 'url' => '/bootstrap', 'verb' => 'POST'],
    ],
];
