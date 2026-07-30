## Why

The non-root review image stores Pi state under `/home/review`, but the
container runner still mounts host authentication at `/root/.pi`. Builds also
fail late with opaque parser errors when BuildKit or compatible Podman support
is unavailable.

## What Changes

- Mount `auth.json` at the non-root Pi home with read-only permissions.
- Fail before image builds when Docker BuildKit or Podman build support is unavailable.
- Document uid 10001 bind-mount ownership and build requirements.
- Rename the CRG analysis test module and regenerate validation counts.

## Capabilities

### New Capabilities

- `container-runtime-hardening`: Define non-root auth mounting and build capability checks.

### Modified Capabilities

- None.
