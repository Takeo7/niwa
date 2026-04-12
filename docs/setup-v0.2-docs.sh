#!/bin/bash
# setup-v0.2-docs.sh
# Coloca los 3 documentos de planning en la rama v0.2 del repo Niwa
# y los commitea.
#
# Uso:
#   1. Descarga SPEC-v0.2.md, DECISIONS-LOG.md y BUGS-FOUND.md al mismo directorio que este script.
#   2. Ejecuta este script desde la raíz del repo clonado (Takeo7/niwa).
#   3. El script crea la rama v0.2 si no existe, coloca los archivos en docs/,
#      hace commit y (opcionalmente) push.

set -e

REPO_ROOT="$(pwd)"
DOCS_DIR="$REPO_ROOT/docs"
FILES_TO_COPY=("SPEC-v0.2.md" "DECISIONS-LOG.md" "BUGS-FOUND.md")

# Verificar que estamos en la raíz del repo
if [ ! -d ".git" ]; then
    echo "Error: ejecuta este script desde la raíz del repo niwa clonado."
    exit 1
fi

# Verificar que los 3 archivos están presentes en el directorio actual o en el del script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for f in "${FILES_TO_COPY[@]}"; do
    if [ ! -f "$SCRIPT_DIR/$f" ] && [ ! -f "./$f" ]; then
        echo "Error: falta el archivo $f. Descárgalo junto a este script."
        exit 1
    fi
done

# Crear/cambiar a rama v0.2
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if git show-ref --verify --quiet refs/heads/v0.2; then
    echo "Rama v0.2 ya existe, cambiando a ella."
    git checkout v0.2
else
    echo "Creando rama v0.2 desde $CURRENT_BRANCH."
    git checkout -b v0.2
fi

# Crear docs/ si no existe
mkdir -p "$DOCS_DIR"

# Copiar los 3 archivos
for f in "${FILES_TO_COPY[@]}"; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        cp "$SCRIPT_DIR/$f" "$DOCS_DIR/$f"
    else
        cp "./$f" "$DOCS_DIR/$f"
    fi
    echo "Copiado: docs/$f"
done

# Stage y commit
git add docs/SPEC-v0.2.md docs/DECISIONS-LOG.md docs/BUGS-FOUND.md
git commit -m "docs(v0.2): spec completa, decision log y bugs log"

echo ""
echo "Commit hecho en local en rama v0.2."
echo ""
echo "Para subir al remoto:"
echo "  git push -u origin v0.2"
echo ""
