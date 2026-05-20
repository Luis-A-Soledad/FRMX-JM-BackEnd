#!/bin/bash
# Activar entorno virtual si usas uno, por ejemplo:
source antenv/bin/activate
echo "Ejecutando migraciones..."
python3 manage.py makemigrations
python3 manage.py migrate
echo "Recolectando archivos estaticos..."
python3 manage.py collectstatic --noinput
echo "Iniciando Daphne..."
python3 -m daphne core.asgi:application --host 0.0.0.0 --port 8000