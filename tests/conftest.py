from typing import Generator

import pytest

from sqlalchemy_utils import create_database, database_exists, drop_database
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from app.db.db import get_db
from app.log import Log
from app.settings import config
from main import get_app

DATABASE_URL = (
    f"postgresql://{config.DB_USER}:{config.DB_PASSWORD}@"
    f"{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}_test"
)


@pytest.fixture(scope="session")
def connection():
    engine = create_engine(DATABASE_URL, echo=False)

    if not database_exists(engine.url):
        create_database(engine.url)

    connection = engine.connect()

    yield connection

    connection.close()
    drop_database(engine.url)


@pytest.fixture(scope="function")
def setup_db(connection, request) -> None:
    """Setup test database.

    Creates all database tables as declared in SQLAlchemy models,
    then proceeds to drop all the created tables after all tests
    have finished running.
    """

    # SQLModel.metadata.bind = connection
    SQLModel.metadata.create_all(bind=connection)

    def teardown():
        SQLModel.metadata.drop_all(bind=connection)

    request.addfinalizer(teardown)

    return None


@pytest.fixture()
def db_session(connection, setup_db, request) -> Session:
    session = Session(bind=connection)
    session.begin_nested()

    def teardown():
        connection.rollback()
        session.close()

    request.addfinalizer(teardown)

    return session


def prepare_tables_in_db(model, db_session=None):
    if db_session is None:
        db_session = next(get_db())
    assert db_session.is_active
    # Add a guard to check environment type
    if config.TARGET_ENV != "local-dev":
        raise Exception(
            "This test is destructive and "
            "only for testing in local development!"
        )

    if model.__table__.exists(db_session.get_bind()):
        # Delete all rows in table
        db_session.query(model).delete()
        db_session.commit()
    else:
        model.__table__.create(db_session.get_bind())

    # Check that the table is empty
    assert db_session.query(model).count() == 0, "Table should be empty"
    return db_session


@pytest.fixture()
def client(
    db_session: Session,
) -> Generator[TestClient, None, None]:
    app = get_app()

    def get_fake_db() -> Session:
        return db_session

    app.dependency_overrides[get_db] = get_fake_db

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def setup_loging():
    """Pytest fixture that sets up logging for tests"""
    Log.setup(application_name="tests")
