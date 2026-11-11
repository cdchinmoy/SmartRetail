"""Run the v1 DDL and structural checks using PostgreSQL's socket-free backend.
Usage: python scripts/verify_schema_standalone.py /path/to/postgresql/bin
Single-user mode implicitly bypasses RLS, so it cannot test isolation behavior.
This supplements, and does not replace, API integration tests.
"""
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import re
from types import SimpleNamespace
from sqlalchemy import create_mock_engine, text

pg_bin = pathlib.Path(sys.argv[1]).resolve()
statements = ['CREATE ROLE smartretail_app NOSUPERUSER NOBYPASSRLS;']
engine = None

def capture(sql, *multiparams, **params):
    if isinstance(sql, str): sql=text(sql)
    if multiparams and multiparams[0]: sql=sql.bindparams(**multiparams[0])
    statements.append(str(sql.compile(dialect=engine.dialect, compile_kwargs={'literal_binds':True})).strip().rstrip(';')+';')

engine=create_mock_engine('postgresql+psycopg://',capture)
spec=importlib.util.spec_from_file_location('foundation',pathlib.Path('alembic/versions/0001_foundation.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.op=SimpleNamespace(get_bind=lambda:engine,execute=capture)
module.upgrade()
statements.append("""
DO $$ BEGIN IF (SELECT count(*) FROM pg_class WHERE relname IN ('branches','warehouses','tenant_memberships','tenant_audit_logs') AND relrowsecurity AND relforcerowsecurity) <> 4 THEN RAISE EXCEPTION 'Missing forced RLS'; END IF; END $$;
DO $$ BEGIN IF (SELECT count(*) FROM permissions) <> 4 OR (SELECT count(*) FROM roles) <> 3 THEN RAISE EXCEPTION 'Invalid RBAC seed'; END IF; END $$;
SELECT 'SCHEMA_CHECKS_PASSED';
""")
# Single-user backend accepts a statement per input line; compact DDL into one line.
source='\n'.join(' '.join(s.split()) for s in statements)+'\n'
with tempfile.TemporaryDirectory(prefix='smartretail-rls-') as tmp:
    data=pathlib.Path(tmp)/'data'
    subprocess.run([str(pg_bin/'initdb'),'-D',str(data),'-A','trust','--no-locale'],capture_output=True,text=True,check=True)
    result=subprocess.run([str(pg_bin/'postgres'),'--single','-D',str(data),'postgres'],input=source,capture_output=True,text=True)
    output=result.stdout+result.stderr
    if result.returncode or re.search(r'\b(ERROR|FATAL|PANIC):',output) or 'SCHEMA_CHECKS_PASSED' not in output:
        print(output);sys.exit(1)
    print('PASS: v1 schema and RBAC seed DDL executed on PostgreSQL; forced RLS flags and RBAC seed checks passed (structure only).')
