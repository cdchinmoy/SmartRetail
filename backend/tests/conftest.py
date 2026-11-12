import os
os.environ.setdefault('DATABASE_URL','postgresql+psycopg://smartretail_app:unused@localhost/smartretail')
os.environ.setdefault('JWT_SECRET','unit-test-only-secret-with-at-least-32-characters')
os.environ.setdefault('SECURE_COOKIES','false')
