import secrets
from pathlib import Path

from flask import Flask
from flask_wtf.csrf import CSRFProtect

from .models import db


csrf = CSRFProtect()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)
    secret_path = instance_path / "secret_key"
    if not secret_path.exists():
        secret_path.write_text(secrets.token_hex(32), encoding="utf-8")
        secret_path.chmod(0o600)
    app.config.from_mapping(
        SECRET_KEY=secret_path.read_text(encoding="utf-8"),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{instance_path / 'finance.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    (instance_path / "import_previews").mkdir(exist_ok=True)
    db.init_app(app)
    csrf.init_app(app)

    from .routes import bp

    app.register_blueprint(bp)
    with app.app_context():
        db.create_all()
        from .services import seed_categories

        seed_categories()

    return app
