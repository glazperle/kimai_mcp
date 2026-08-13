<?php

/*
 * This file is part of the Kimai MCP server project.
 *
 * For the full copyright and license information, please view the LICENSE
 * file that was distributed with this source code.
 */

namespace KimaiPlugin\ApiTokenBundle\DependencyInjection;

use Symfony\Component\Config\FileLocator;
use Symfony\Component\DependencyInjection\ContainerBuilder;
use Symfony\Component\DependencyInjection\Loader;
use Symfony\Component\HttpKernel\DependencyInjection\Extension;

/**
 * Loads the bundle's service definitions.
 *
 * Symfony only picks up Resources/config/services.yaml through an extension
 * whose class name matches the bundle (ApiTokenBundle -> ApiTokenExtension).
 * Without it the routes still resolve, but the controller is not a service, so
 * every request dies with "has required constructor arguments and does not
 * exist in the container".
 */
class ApiTokenExtension extends Extension
{
    public function load(array $configs, ContainerBuilder $container): void
    {
        $loader = new Loader\YamlFileLoader($container, new FileLocator(__DIR__ . '/../Resources/config'));
        $loader->load('services.yaml');
    }
}
