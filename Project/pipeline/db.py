"""PostgreSQL connection shared by the pipeline and the dashboard.

Defaults match docker-compose.yml; set DATABASE_URL to point somewhere else.
"""

import os

from sqlalchemy import create_engine

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://bank:bank@localhost:5432/bank")


def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)
