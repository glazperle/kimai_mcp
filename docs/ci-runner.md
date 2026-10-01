# CI auf dem eigenen Runner

Dieses Repository ist **öffentlich** und bleibt deshalb **auf GitHub**. Es wird nicht an den selbst
gehosteten Runner auf dem FINDER-Host angebunden: Bei einem öffentlichen Repository könnte jede
Person über einen Pull Request Code auf dem Host ausführen.

Die Workflows bleiben unverändert auf `ubuntu-latest`. Die Variable `CI_RUNNER_LABELS` wird hier
nicht gesetzt.

Die vollständige Anleitung zu den Runnern, ihrem Sicherheitsmodell und den angebundenen Repositories
liegt in `glazperle/server`, `docs/ci-runner.md`.
