# Arquitectura inicial de Desk

## Propuesta

- Frontend web separado
- Backend API local
- Base de datos local en el VPS
- Reverse proxy en subdominio `desk.yumewagener.com`
- Integraciones controladas por n8n o sincronización local

## Modelo de seguridad

- Desk almacena datos ya permitidos para Yume
- Yume no necesita acceso directo universal a cuentas personales
- Salidas limitadas a canales permitidos
- Escaneo local para contenido importado cuando aplique
