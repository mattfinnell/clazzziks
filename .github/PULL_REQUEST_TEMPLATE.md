<!--
PR title: keep it scoped, e.g. "backend: fix SoundCloud DRM error message".
Branch: {scope}/{description} where scope ∈ backend, frontend, infra, docs.
-->

## Summary

<!-- What does this PR do, and why? One or two sentences. -->

## Area

<!-- The scope(s) this touches: backend / frontend / infra / docs -->

## Changes

<!-- The notable changes, as bullets. -->

-

## Related

- Closes #

## How tested

<!-- Commands run, manual steps, and screenshots/GIFs for UI changes. -->

-

## Checklist

- [ ] Pre-commit hooks pass
- [ ] Tests added/updated and passing (`uv run pytest -m "not e2e"` for backend)
- [ ] No secrets, `.env` files, or Firebase service account JSON committed

<details>
<summary>If the API contract changed</summary>

- [ ] Updated `backend/clazzziks/openapi.json` by hand
- [ ] `uv run pytest tests/test_contract.py` passes
- [ ] Auth-protected routes have `security` + `401`/`403` responses documented
</details>

<details>
<summary>If the database changed</summary>

- [ ] No PII beyond `email` added to `track_cache` / `vip` / `download_log`
- [ ] Rate-limit / VIP semantics unchanged unless explicitly intended
</details>

<details>
<summary>If infra (`infra/`) changed</summary>

- [ ] `cd infra && npx tsc --noEmit` passes
- [ ] Ran `pulumi preview` against the affected stack and reviewed the diff
- [ ] Resource name strings kept stable when moving code between `components/*.ts` files
- [ ] Config keys added to both `Pulumi.staging.yaml` and `Pulumi.production.yaml`
</details>
