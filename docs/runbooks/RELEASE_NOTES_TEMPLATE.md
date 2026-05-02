# Niwa Release Notes Template

Version: ``
Date: ``
Commit: ``

## Summary

- 

## Operator Upgrade Notes

- Run `./bootstrap.sh`.
- Run `make release-gate`.
- Run `niwa-executor doctor --strict` before exposing Niwa online.

## Gates

```text
cd backend && pytest -q
<paste literal output>
```

```text
cd frontend && npm test -- --run
<paste literal output>
```

```text
make smoke
<paste literal output>
```

```text
make release-gate
<paste literal output>
```

## Known Limitations

- 

## Rollback

- Stop services with `niwa-executor stop`.
- Restore a known-good backup with `niwa-executor restore <archive> --yes`.
