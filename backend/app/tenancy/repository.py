from sqlalchemy import select
from app.models import Branch

class BranchRepository:
    def __init__(self, db, tenant_id):
        self.db, self.tenant_id = db, tenant_id
    def list(self, offset, limit):
        return self.db.scalars(select(Branch).where(Branch.tenant_id == self.tenant_id).order_by(Branch.name, Branch.id).offset(offset).limit(limit)).all()
    def get(self, branch_id):
        return self.db.scalar(select(Branch).where(Branch.tenant_id == self.tenant_id, Branch.id == branch_id))
    def create(self, name):
        branch = Branch(tenant_id=self.tenant_id, name=name)
        self.db.add(branch); self.db.flush()
        return branch
