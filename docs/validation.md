# Validation record

Built on 2026-11-17 with Python 3.12.14 on Windows.

- Eight automated tests passed for this service.
- Dependencies are pinned to the versions used in this build.
- The Dockerfile and GitHub workflow are included. A local Docker engine is not installed;
  image build verification runs in GitHub Actions.
- No paid live-model calls were made.
- Interactive Chrome checks passed against the actual local Python API.
- All four browser interfaces passed 390px horizontal-overflow checks with no script errors.
- Render reports the deployment as live. Public health and functional API checks passed.
- GitHub Actions passed Python 3.12/3.13 tests and built the Docker image.
- Live app: https://realtime-fraud-detection-iosi.onrender.com
- Verification details: `cloud-verification.json`.

Limitations and measured behavior are described in the README. This implementation
does not validate the workload sizes or performance figures in the source resume.
