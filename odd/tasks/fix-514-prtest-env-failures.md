# fix-514-prtest-env-failures

Issue: https://github.com/alexandervazquez98/next-gen/issues/514
Branch: `fix/issue-514-prtest-env-failures` (created from `origin/main` @ `793450ec`)
Worktree: `.worktrees/issue-514-prtest-env-failures`
Strategy: **Hybrid** (bind-mounts + `env_required` marker + skip-when-missing guards) — issue recommends this combination; pure bind-mounts couples tests to host layout, pure refactor is too invasive for 7 unrelated test files.

## Goal

Eliminar los **20 fallos crónicos pre-existentes** de pytest en el entorno `nextgen-prtest` (issue #514) sin acoplarlos al host layout. Restaurar el verdict PASS para `pytest tests/` cuando los tests corren en prtest, y documentar qué markers se necesitan para tests que genuinamente requieren Docker daemon o binarios externos.

## Decisiones tomadas

| # | Decisión | Default | Por qué |
|---|---|---|---|
| 1 | Estrategia de fix | Híbrido (bind-mounts + markers + skip-when-missing) | La propia issue recomienda esta combinación: bind-mount para resolver paths, markers para docker.sock/pg_dump, skip para fixtures que no existen en main |
| 2 | Nombre del nuevo marker pytest | `env_required` | Sigue patrón existente (`unit`, `integration`, `slow`, `neo4j`, `metric`, `event`, `auth`, `api`) — autoexplicativo |
| 3 | Tests que reciben `@pytest.mark.env_required` | `test_writer_advisory_lock.py` (4 tests con testcontainers), `test_backup_service.py::TestPgDump` (1 test con subprocess pg_dump) | Requieren Docker daemon real o binarios externos que no pertenecen al contenedor de aplicación |
| 4 | Tests con guard `pytest.skip(reason=...)` cuando el recurso falta | `test_spec_coverage_graph.py` (spec vive en branch `feat-390-lod-contracts`, no en main), `test_graph_full_snapshot.py` (fixture `frozen_response.json` no commiteado), `test_refresh_token_activity_backfill.py` (fixture helper falta hasta que PR0 #287 mergee) | Skip en lugar de fail evita regresión de coverage cuando el change aún no mergeó |
| 5 | Bind-mounts nuevos en `docker-compose.yml` | `./backend:/backend:ro`, `./backend/tests/fixtures:/fixtures:ro`, `./openspec:/openspec:ro`, `./docs:/docs:ro`, `./README.md:/README.md:ro` | Resuelve el path `parents[2] = /` que asumen los tests cuando corren dentro del contenedor |
| 6 | `docker-compose.prtest.yml` override nuevo | Sí, con `/var/run/docker.sock:/var/run/docker.sock` (sólo en prtest, security) | El socket de docker NUNCA debe montarse en prod; prtest-only override lo aísla |
| 7 | Documentación | Nuevo `docs/testing-environment.md` describe: qué marker usar cuándo, cómo correr prtest, qué tests requieren qué entorno | Para que futuros autores no vuelvan a introducir fallos ambientales |
| 8 | `test_research_hashtext_collisions.py` | NO tocar el código del test. Sólo arreglar con bind-mount `/backend` → `./backend` | El test es correcto cuando corre desde host (parents[2] = repo root); sólo falla por path mismatch en container |
| 9 | `test_polling_docs_links.py` | NO tocar el código del test. Sólo arreglar con bind-mounts `/docs`, `/README.md` | Mismo razonamiento |
| 10 | OpenSpec change directory | NO crear (`openspec/changes/fix-514-prtest-env-failures/`). Sólo `odd/tasks/` | Es un bug fix infra, no un feature change; el archivo `odd/tasks/` cubre el tracking |

## Scope (lo que se hace)

### A. `docker-compose.yml` — añadir 5 volumes al servicio `backend`

```yaml
volumes:
  - ${BACKUP_DIR:-.docker/backups}:/backups
  - ${AI_PROMPTS_DIR_HOST:-.docker/ai}:/data/ai
  # Fix #514 — bind-mounts para tests prtest
  - ./backend:/backend:ro                                    # resolve `parents[2]=/` paths
  - ./backend/tests/fixtures:/fixtures:ro                    # snapshot fixtures
  - ./openspec:/openspec:ro                                  # spec_coverage tests
  - ./docs:/docs:ro                                          # docs link tests
  - ./README.md:/README.md:ro                                # polling docs links test
```

### B. `docker-compose.prtest.yml` — NUEVO archivo

Override exclusivo para prtest. Monta docker.sock (necesario para `testcontainers[postgres]`), define `.env.prtest`, y opcionalmente override del comando de test.

```yaml
services:
  backend:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # for test_writer_advisory_lock.py only
    environment:
      - PRTEST_FIXTURES_ENABLED=true
    command: ["python", "-m", "pytest", "tests/", "-q", "--no-header", "--tb=line"]
```

### C. `backend/pytest.ini` — añadir marker `env_required`

```ini
markers =
    ...
    env_required: Tests requiring a fully-fitted environment (Docker socket, pg_dump binary, etc.). Skipped by default; opt in with `-m env_required` or run inside the prtest container.
```

### D. `backend/tests/test_writer_advisory_lock.py` — `@pytest.mark.env_required` en los 4 tests con `testcontainers`

Líneas aproximadas: 671, 800, 901, 1003 (los 4 que hacen `from testcontainers.postgres import PostgresContainer`).

### E. `backend/tests/test_backup_service.py` — `@pytest.mark.env_required` en `TestPgDump`

3 tests (líneas 325, 352, 380 aprox) que invocan `pg_dump` como subprocess.

### F. `backend/tests/test_spec_coverage_graph.py` — guard `pytest.skip` cuando el spec no existe

En `test_spec_file_exists`: `pytest.skip(reason="feat-390-lod-contracts spec only exists on its feature branch; skipped on main")` si el spec no se encuentra.

### G. `backend/tests/test_graph_full_snapshot.py` — guard `pytest.skip` cuando fixture no existe

Si `fixtures/graph-full/frozen_response.json` no está, los 5 tests skip con mensaje claro.

### H. `backend/tests/test_refresh_token_activity_backfill.py` — investigar el fixture faltante

Verificar cuál es y aplicar guard `pytest.skip` si es legítimo que no exista en main (es PR0 de #287, puede no haber mergeado).

### I. `docs/testing-environment.md` — NUEVO archivo

Documenta:
- Qué tests requieren qué entorno
- Cómo correr pytest localmente vs prtest
- Cómo agregar nuevos tests con dependencias ambientales
- Convenciones de marker

## Scope (lo que NO se hace)

- **NO** se refactoriza ningún test para usar `tmp_path` o `monkeypatch` (issue Option 2). Es invasivo, alto riesgo de regresiones, y el bind-mount es suficiente.
- **NO** se modifica `backend/Dockerfile`. Los volúmenes lo resuelven.
- **NO** se commitea la fixture `frozen_response.json` ni el spec de #390 en este PR. Pertenecen a sus changes respectivos.
- **NO** se actualiza el `docker-compose.prod.yml` ni el servicio `backend` de prod. El socket de docker NUNCA debe llegar a prod.

## Plan de tasks (single PR, ~250-300 líneas estimadas)

1. Añadir `env_required` marker a `backend/pytest.ini`. Commit: `test(env): add env_required marker`.
2. Crear `docker-compose.prtest.yml` con override de docker.sock. Commit: `test(env): add docker-compose.prtest.yml override`.
3. Añadir 5 volumes al servicio `backend` en `docker-compose.yml`. Commit: `fix(env): bind-mount paths required by prtest tests (#514)`.
4. Marcar 4 tests en `test_writer_advisory_lock.py` con `@pytest.mark.env_required`. Commit: `test(env): mark advisory-lock testcontainers tests as env_required (#514)`.
5. Marcar 3 tests en `test_backup_service.py::TestPgDump` con `@pytest.mark.env_required`. Commit: `test(env): mark pg_dump subprocess tests as env_required (#514)`.
6. Añadir guard `pytest.skip` en `test_spec_coverage_graph.py::test_spec_file_exists` cuando el spec no existe. Commit: `test(env): skip spec-coverage gate when spec absent (#514)`.
7. Añadir guard `pytest.skip` en `test_graph_full_snapshot.py` cuando fixture no existe. Commit: `test(env): skip graph-full snapshot tests when fixture absent (#514)`.
8. Investigar y resolver el fixture faltante en `test_refresh_token_activity_backfill.py`. Commit: `test(env): skip backfill test when helper missing (#514)`.
9. Crear `docs/testing-environment.md` con la guía de markers y entornos. Commit: `docs(env): document test markers and prtest environment (#514)`.
10. Verificar: ejecutar pytest localmente y validar que los markers + skip guards funcionan. NO podemos correr prtest en este entorno, pero podemos verificar el comportamiento del pytest local.
11. Verificar: `git diff --check`, linting, formato. Commit final si hay fixups.

## Acceptance criteria

- `pytest backend/tests/` corre en local sin esos 20 fallos (los tests marcados como `env_required` se skip por default; los guardados con skip no fallan).
- Con `-m env_required` desde local, los tests marcados siguen skip (no tenemos docker daemon aquí, eso está OK — verifica que el marker es respected).
- El nuevo `docker-compose.prtest.yml` es sintácticamente válido (`docker compose -f docker-compose.yml -f docker-compose.prtest.yml config` debe pasar).
- El `docker-compose.yml` base sigue arrancando correctamente (los nuevos volumes son `ro` y apuntan a paths que existen en el repo).
- `docs/testing-environment.md` explica claramente la convención.
- El budget de 400 líneas NO se excede (estimado: ~250-300).

## Riesgos clave

1. **El bind-mount `./backend:/backend:ro` puede ocultar archivos generados por el build del contenedor.** Mitigación: `:ro` (read-only) — el build no escribe en `/backend`. Si algo necesita escribir, va por `/app` (que es donde WORKDIR apunta).
2. **El override `docker-compose.prtest.yml` puede tener drift respecto al `docker-compose.yml` base.** Mitigación: usar `merge` style de docker compose (sólo override lo que cambia).
3. **Marcadores `env_required` pueden skip silenciar regresiones reales.** Mitigación: el marcador es opt-in (`-m env_required`), y prtest siempre corre con `-m env_required` para no skip esos tests.
4. **El test de `test_spec_coverage_graph.py` skip en main podría falsear el coverage gate.** Mitigación: el coverage gate es por branch de feature (`feat-390-lod-contracts`), no por main. En CI el gate corre en la branch correcta, donde el spec SÍ está commiteado.

## Referencias

- Issue: https://github.com/alexandervazquez98/next-gen/issues/514
- Tests afectados: `backend/tests/test_research_hashtext_collisions.py`, `test_spec_coverage_graph.py`, `test_writer_advisory_lock.py`, `test_graph_full_snapshot.py`, `test_polling_docs_links.py`, `test_refresh_token_activity_backfill.py`, `test_backup_service.py`
- Config relevante: `docker-compose.yml`, `docker-compose.prod.yml`, `backend/Dockerfile`, `backend/pytest.ini`
- OpenSpec config: `openspec/config.yaml` (`review_budget_changed_lines: 400`, `strict_tdd.test_first_required: true`)
- Precedent de bug infra fix: `fix-508-auth-cookie-test-isolation`, `fix-497-geo-view-osm-tiles`