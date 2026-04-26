# PR-V1-30 — `bootstrap.sh` activa linger en Linux

**Tipo:** UX FIX
**Esfuerzo:** S
**Depende de:** ninguna

## Qué

En Linux, los systemd user services no arrancan al boot a menos
que el usuario tenga linger activado (`loginctl enable-linger
<user>`). Sin esto, tras reboot del PC, `niwa-executor` no se
levanta hasta que el usuario hace login en una sesión gráfica o
SSH. Bootstrap debe hacerlo automáticamente.

## Por qué

Smoke real 2026-04-25: tras reboot del PC de la pareja del
autor, tuvo que ejecutar manualmente `niwa-executor start`. La
expectativa razonable es que arranque solo.

## Scope

```
bootstrap.sh                              # +5 LOC bloque Linux
docs/plans/FOUND-20260422-onboarding.md   # marcar fricción 7 cerrada
```

**Hard-cap: 30 LOC.**

## Contrato

En `bootstrap.sh`, justo después de escribir el systemd user
unit en Linux (paso 8 actual), añadir:

```bash
case "$(uname -s)" in
    Linux)
        # Enable lingering so the user service survives reboots
        # without requiring a graphical/SSH login. Needs sudo.
        if ! loginctl show-user "$USER" 2>/dev/null | \
             grep -q '^Linger=yes'; then
            _log "enabling user linger (requires sudo password)"
            sudo loginctl enable-linger "$USER" \
                && _log "linger enabled" \
                || _log "WARN: enable-linger failed; service will not
                          autostart on reboot. Run manually:
                          sudo loginctl enable-linger $USER"
        else
            _log "linger already enabled"
        fi
        ;;
esac
```

El `sudo` puede fallar si el usuario no tiene permiso o no
introduce password. En ese caso el bootstrap NO falla — emite
warning y sigue. El usuario puede ejecutar el comando después.

## Fuera de scope

- macOS: launchd ya tiene `RunAtLoad=true` en el plist, autostart
  funciona sin cambios.
- Hacer el comando opcional con flag `--no-linger`: por ahora
  siempre intenta, falla suave.

## Criterio de hecho

- [ ] En Ubuntu, tras `./bootstrap.sh`, `loginctl show-user $USER`
      reporta `Linger=yes`.
- [ ] Tras reboot, `systemctl --user is-active niwa-executor`
      devuelve `active`.
- [ ] Bootstrap no aborta si `sudo enable-linger` falla.
