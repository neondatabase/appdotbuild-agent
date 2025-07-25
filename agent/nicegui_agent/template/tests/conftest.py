from typing import Generator
import pytest
from app.startup import startup
from nicegui.testing import User

pytest_plugins = ["nicegui.testing.plugin"]


@pytest.fixture
def user(user: User) -> Generator[User, None, None]:
    startup()
    yield user
