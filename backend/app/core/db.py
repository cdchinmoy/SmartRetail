from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

def db_session():
    # Every request gets exactly one transaction, including SET LOCAL context.
    with SessionLocal.begin() as db:
        yield db

def context(db, name, value):
    assert name in {'app.user_id', 'app.tenant_id'}
    db.execute(text('SELECT set_config(:key, :value, true)'), {'key': name, 'value': str(value)})
