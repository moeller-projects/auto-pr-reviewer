## ADDED Requirements

### Requirement: Non-root Pi authentication mount

The container operation MUST mount an existing host Pi `auth.json` at
`/home/review/.pi/agent/auth.json` with read-only permissions when the review
container runs as user `review`.

#### Scenario: Host auth file is present

- **WHEN** an operator runs a container command with an existing `auth.json`
- **THEN** the generated command MUST contain
  `/home/review/.pi/agent/auth.json:ro` and MUST NOT target `/root/.pi`

### Requirement: Build capability guard

The build operation MUST verify the selected runtime supports the Dockerfile's
cache and bind mounts before invoking the image build.

#### Scenario: Docker BuildKit is disabled

- **WHEN** `DOCKER_BUILDKIT=0` is set for a Docker build
- **THEN** the operation MUST fail with an actionable BuildKit error before
  invoking Docker

#### Scenario: Podman is selected

- **WHEN** Podman is selected for an image build
- **THEN** the operation MUST require Podman 4.0 or newer and set
  `BUILDAH_FORMAT=docker` before invoking the build
