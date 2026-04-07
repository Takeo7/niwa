#!/bin/bash
# fix-cookie-domain.sh — Aplica el fix crítico de Domain en cookies de app.py
# Este script modifica las líneas de Set-Cookie para añadir Domain=.yumewagener.com y Secure
#
# Uso: bash scripts/fix-cookie-domain.sh
# Verificación: bash scripts/fix-cookie-domain.sh --dry-run

set -euo pipefail

APP_PY="/home/yume/.openclaw/workspace/Desk/backend/app.py"
BACKUP="${APP_PY}.bak.$(date +%Y%m%d%H%M%S)"

if [ ! -f "$APP_PY" ]; then
    echo "ERROR: No se encuentra $APP_PY"
    exit 1
fi

DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
    echo "=== DRY RUN — no se aplicarán cambios ==="
fi

# Verificar que las líneas objetivo existen (sin Domain)
LOGIN_MATCH=$(grep -c "Set-Cookie.*desk_session.*Path=/; HttpOnly; SameSite=Lax; Max-Age=" "$APP_PY" || true)
LOGOUT_MATCH=$(grep -c "Set-Cookie.*desk_session=;.*Path=/; HttpOnly; SameSite=Lax; Max-Age=0" "$APP_PY" || true)

if [ "$LOGIN_MATCH" -eq 0 ] && [ "$LOGOUT_MATCH" -eq 0 ]; then
    echo "INFO: No se encontraron líneas de Set-Cookie sin Domain."
    echo "      El fix puede estar ya aplicado."
    grep -n "Set-Cookie.*desk_session" "$APP_PY" || true
    exit 0
fi

echo "Encontradas $LOGIN_MATCH línea(s) de login y $LOGOUT_MATCH línea(s) de logout para parchear."

if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "--- CAMBIOS QUE SE APLICARÍAN ---"
    echo ""
    echo "Login (Set-Cookie en respuesta de login):"
    echo "  ANTES: Path=/; HttpOnly; SameSite=Lax; Max-Age=..."
    echo "  DESPUÉS: Domain=.yumewagener.com; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=..."
    echo ""
    echo "Logout (Set-Cookie para borrar cookie):"
    echo "  ANTES: Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
    echo "  DESPUÉS: Domain=.yumewagener.com; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0"
    echo ""
    echo "Ejecuta sin --dry-run para aplicar."
    exit 0
fi

# Crear backup
cp "$APP_PY" "$BACKUP"
echo "Backup creado: $BACKUP"

# Aplicar fix: añadir Domain=.yumewagener.com; y Secure; antes de SameSite
# Login cookie (tiene Max-Age dinámico)
sed -i "s|Path=/; HttpOnly; SameSite=Lax; Max-Age={\(DESK_SESSION_TTL_HOURS\)|Domain=.yumewagener.com; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={\1|g" "$APP_PY"

# Logout cookie (Max-Age=0 fijo)
sed -i "s|Path=/; HttpOnly; SameSite=Lax; Max-Age=0|Domain=.yumewagener.com; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0|g" "$APP_PY"

# Verificar
echo ""
echo "=== VERIFICACIÓN ==="
grep -n "Set-Cookie.*desk_session" "$APP_PY"
echo ""
echo "Fix aplicado correctamente."
echo "Próximos pasos:"
echo "  1. docker compose restart desk"
echo "  2. Borrar cookies de desk.yumewagener.com en el navegador"
echo "  3. Iniciar sesión de nuevo"
echo "  4. Verificar que invest/pumicon/terminal/n8n/trendflow cargan sin unauthorized"
