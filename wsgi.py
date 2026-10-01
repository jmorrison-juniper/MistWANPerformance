"""
WSGI entry point for the MistWANPerformance dashboard.

Gunicorn can load the app from this module:
    gunicorn -c gunicorn_config.py wsgi:server

The container starts the same app with:
    gunicorn -c gunicorn_config.py "run_dashboard:create_wsgi_app()"

Both commands build the app with run_dashboard.create_wsgi_app(), so they
load the same configuration and start the same background workers.
"""

from run_dashboard import create_wsgi_app

server = create_wsgi_app()
