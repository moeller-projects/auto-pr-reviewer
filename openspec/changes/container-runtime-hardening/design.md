## Context

ReviewForge builds images with Dockerfile `RUN --mount` cache and bind
mounts, then runs Pi as uid 10001. The host auth file is an input only and
must not be writable from the container.

## Decisions

- Pre-create `/home/review/.pi/agent` and assign it to `review` in the image.
- Mount the host auth file at `/home/review/.pi/agent/auth.json:ro`.
- Probe Docker Buildx before Docker builds and require Podman 4 or newer with
  `BUILDAH_FORMAT=docker` before Podman builds.
- Keep the guard in `reviewforge.ops` so every build caller shares the same
  failure behavior.

## Risks and Rollback

The build guard intentionally rejects unsupported runtimes before invoking a
build. Operators can use a supported runtime or unset an obsolete
`DOCKER_BUILDKIT=0`; reverting the ops and Dockerfile changes restores the
previous command construction.
