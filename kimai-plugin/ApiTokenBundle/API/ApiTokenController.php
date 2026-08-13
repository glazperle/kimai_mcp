<?php

/*
 * This file is part of the Kimai MCP server project.
 *
 * For the full copyright and license information, please view the LICENSE
 * file that was distributed with this source code.
 */

namespace KimaiPlugin\ApiTokenBundle\API;

use App\API\BaseApiController;
use App\Entity\AccessToken;
use App\Entity\User;
use App\Repository\AccessTokenRepository;
use OpenApi\Attributes as OA;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\HttpKernel\Exception\BadRequestHttpException;
use Symfony\Component\Routing\Attribute\Route;
use Symfony\Component\Security\Http\Attribute\IsGranted;

/**
 * Creates personal API tokens on behalf of a user.
 *
 * Kimai's REST API can only DELETE access tokens (`DELETE /api/users/api-token/{id}`);
 * creating one is a web-form-only action (ProfileController::createAccessToken).
 * That leaves automated onboarding no choice but to scrape an admin web session,
 * so this bundle exposes the same operation as a normal API endpoint, with the
 * very same permission check Kimai's own UI performs (`api-token` voter, i.e.
 * `api-token_other_profile`, which only ROLE_SUPER_ADMIN holds by default).
 *
 * The token value is returned exactly once, in the creation response - it is
 * stored in plaintext, but Kimai never renders it again after this point.
 */
#[Route(path: '/users')]
#[IsGranted('API')]
#[OA\Tag(name: 'User')]
final class ApiTokenController extends BaseApiController
{
    /**
     * Length of the generated token, matching ProfileController::createAccessToken().
     */
    private const TOKEN_LENGTH = 25;
    private const NAME_MIN_LENGTH = 2;
    private const NAME_MAX_LENGTH = 50;
    private const DEFAULT_NAME = 'API token';

    public function __construct(
        private readonly AccessTokenRepository $accessTokenRepository,
    ) {
    }

    /**
     * List the API tokens of a user (metadata only, never the token itself)
     */
    #[OA\Response(
        response: 200,
        description: 'Returns the API token metadata of the given user. Required permission: api-token',
        content: new OA\JsonContent(
            type: 'array',
            items: new OA\Items(
                properties: [
                    new OA\Property(property: 'id', type: 'integer'),
                    new OA\Property(property: 'name', type: 'string'),
                    new OA\Property(property: 'lastUsage', type: 'string', format: 'date-time', nullable: true),
                    new OA\Property(property: 'expiresAt', type: 'string', format: 'date-time', nullable: true),
                ],
                type: 'object'
            )
        )
    )]
    #[OA\Parameter(name: 'id', description: 'User ID whose tokens are listed', in: 'path', required: true)]
    #[Route(methods: ['GET'], path: '/{id}/api-token', name: 'get_api_tokens', requirements: ['id' => '\d+'])]
    public function listApiTokens(User $profile): Response
    {
        $this->assertCanManageTokensOf($profile);

        $tokens = array_map(
            fn (AccessToken $token) => $this->serializeToken($token),
            $this->accessTokenRepository->findForUser($profile)
        );

        return new JsonResponse($tokens);
    }

    /**
     * Create an API token for a user and return it once
     */
    #[OA\Response(
        response: 201,
        description: 'The created API token. The "token" value is only ever returned here. Required permission: api-token',
        content: new OA\JsonContent(
            properties: [
                new OA\Property(property: 'id', type: 'integer'),
                new OA\Property(property: 'name', type: 'string'),
                new OA\Property(property: 'token', type: 'string'),
                new OA\Property(property: 'lastUsage', type: 'string', format: 'date-time', nullable: true),
                new OA\Property(property: 'expiresAt', type: 'string', format: 'date-time', nullable: true),
            ],
            type: 'object'
        )
    )]
    #[OA\Parameter(name: 'id', description: 'User ID to create the token for', in: 'path', required: true)]
    #[OA\RequestBody(content: new OA\JsonContent(
        properties: [
            new OA\Property(property: 'name', type: 'string', description: 'Token name shown in the user profile (2-50 characters)'),
            new OA\Property(property: 'expiresAt', type: 'string', format: 'date-time', nullable: true, description: 'Optional expiration date (Y-m-d or ISO 8601)'),
            new OA\Property(property: 'replaceExisting', type: 'boolean', description: 'Delete the user\'s existing tokens with the same name first'),
        ],
        type: 'object'
    ))]
    #[Route(methods: ['POST'], path: '/{id}/api-token', name: 'post_api_token', requirements: ['id' => '\d+'])]
    public function createApiToken(User $profile, Request $request): Response
    {
        $this->assertCanManageTokensOf($profile);

        $payload = $this->decodeBody($request);
        $name = $this->readName($payload);
        $expiresAt = $this->readExpiresAt($payload);
        // filter_var, not a (bool) cast: the string "false" casts to true, so a
        // client sending {"replaceExisting": "false"} would get the opposite of
        // what it asked for and have its existing token deleted.
        $replaceExisting = filter_var(
            $payload['replaceExisting'] ?? false,
            \FILTER_VALIDATE_BOOL,
            \FILTER_NULL_ON_FAILURE
        ) ?? false;

        if ($replaceExisting) {
            foreach ($this->accessTokenRepository->findForUser($profile) as $existing) {
                if ($existing->getName() === $name) {
                    $this->accessTokenRepository->deleteAccessToken($existing);
                }
            }
        }

        $accessToken = new AccessToken($profile, substr(bin2hex(random_bytes(100)), 0, self::TOKEN_LENGTH));
        $accessToken->setName($name);
        if ($expiresAt !== null) {
            $accessToken->setExpiresAt($expiresAt);
        }

        $this->accessTokenRepository->saveAccessToken($accessToken);

        return new JsonResponse(
            $this->serializeToken($accessToken) + ['token' => $accessToken->getToken()],
            Response::HTTP_CREATED
        );
    }

    /**
     * The same two checks Kimai performs in UserController::deleteApiToken():
     * the caller needs token access at all, and access to this profile in
     * particular (`api-token_other_profile` for anyone but themselves).
     */
    private function assertCanManageTokensOf(User $profile): void
    {
        if (!$this->isGranted('api-token', $this->getUser())) {
            throw $this->createAccessDeniedException('User has no access to API tokens');
        }

        if (!$this->isGranted('api-token', $profile)) {
            throw $this->createAccessDeniedException('You are not allowed to manage the API tokens of this user');
        }
    }

    /**
     * @return array<string, mixed>
     */
    private function decodeBody(Request $request): array
    {
        $content = $request->getContent();
        if ($content === '') {
            return [];
        }

        try {
            $payload = json_decode($content, true, 512, \JSON_THROW_ON_ERROR);
        } catch (\JsonException $e) {
            throw new BadRequestHttpException('Invalid JSON body: ' . $e->getMessage());
        }

        if (!\is_array($payload)) {
            throw new BadRequestHttpException('Request body must be a JSON object');
        }

        return $payload;
    }

    /**
     * @param array<string, mixed> $payload
     */
    private function readName(array $payload): string
    {
        $name = $payload['name'] ?? self::DEFAULT_NAME;
        if (!\is_string($name)) {
            throw new BadRequestHttpException('"name" must be a string');
        }

        $name = trim($name);
        $length = mb_strlen($name);
        if ($length < self::NAME_MIN_LENGTH || $length > self::NAME_MAX_LENGTH) {
            throw new BadRequestHttpException(
                \sprintf('"name" must be between %d and %d characters', self::NAME_MIN_LENGTH, self::NAME_MAX_LENGTH)
            );
        }

        return $name;
    }

    /**
     * @param array<string, mixed> $payload
     */
    private function readExpiresAt(array $payload): ?\DateTimeImmutable
    {
        $raw = $payload['expiresAt'] ?? null;
        if ($raw === null || $raw === '') {
            return null;
        }

        if (!\is_string($raw)) {
            throw new BadRequestHttpException('"expiresAt" must be a date string');
        }

        try {
            $date = new \DateTimeImmutable($raw);
        } catch (\Exception $e) {
            throw new BadRequestHttpException('"expiresAt" is not a valid date: ' . $e->getMessage());
        }

        if ($date <= new \DateTimeImmutable()) {
            throw new BadRequestHttpException('"expiresAt" must be in the future');
        }

        return $date;
    }

    /**
     * @return array<string, mixed>
     */
    private function serializeToken(AccessToken $token): array
    {
        return [
            'id' => $token->getId(),
            'name' => $token->getName(),
            'lastUsage' => $token->getLastUsage()?->format(self::DATE_FORMAT_PHP),
            'expiresAt' => $token->getExpiresAt()?->format(self::DATE_FORMAT_PHP),
        ];
    }
}
