"""Точка входа веб-сервера: gunicorn server:app или python server.py."""

import config
from webapp import create_app

app = create_app()


if __name__ == "__main__":
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)
