import pytest
from sqlalchemy.orm import Session

from dikas.db import erstelle_engine, init_db


@pytest.fixture
def session():
    engine = erstelle_engine(":memory:")
    init_db(engine)
    with Session(engine) as s:
        yield s
