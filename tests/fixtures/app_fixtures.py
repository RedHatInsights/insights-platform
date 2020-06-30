import pytest

from app import create_app
from app import db
from app.config import RuntimeEnvironment
from tests.helpers.db_utils import clean_tables


@pytest.fixture(scope="session")
def new_flask_app(database):
    app = create_app(RuntimeEnvironment.TEST)

    with app.app_context() as ctx:
        db.create_all()
        ctx.push()

        yield app

        ctx.pop()
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope="function")
def flask_app(new_flask_app):
    yield new_flask_app

    clean_tables()


@pytest.fixture(scope="function")
def inventory_config(flask_app):
    return flask_app.config["INVENTORY_CONFIG"]
