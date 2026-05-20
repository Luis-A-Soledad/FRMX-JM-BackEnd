#!/bin/bash
# Activar entorno virtual si usas uno, por ejemplo:
source antenv/bin/activate
echo "Ejecutando migraciones..."
python3 manage.py makemigrations
python3 manage.py migrate
echo "Recolectando archivos estaticos..."
python3 manage.py collectstatic --noinput
echo "Iniciando Gunicorn..."
python3 -m gunicorn core.wsgi:application -c gunicorn.conf.py