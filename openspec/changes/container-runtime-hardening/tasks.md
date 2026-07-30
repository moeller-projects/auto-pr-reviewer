## 1. Container Runtime

- [x] 1.1 Pre-create the non-root Pi agent directory in the runtime image.
- [x] 1.2 Mount host authentication at the non-root path read-only.
- [x] 1.3 Guard Docker BuildKit and Podman build capability before builds.
- [x] 1.4 Preserve build dry-run previews without capability probes.

## 2. Documentation and Tests

- [x] 2.1 Document uid 10001 bind-mount ownership and build requirements.
- [x] 2.2 Update operation tests for auth mounts and capability guards.
- [x] 2.3 Rename the CRG analysis test and regenerate validation counts.
- [x] 2.4 Run targeted and full test coverage verification.
