import os
from alembic import context
from sqlalchemy import create_engine
from app.models import Base
from app.billing import models  # register billing metadata
config = context.config
engine = create_engine(os.environ['MIGRATION_DATABASE_URL'])
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
