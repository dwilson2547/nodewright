"""revision labels

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-11 17:18:36.024036
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('canvas_revisions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('label', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('restored_from', sa.Integer(), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('canvas_revisions', schema=None) as batch_op:
        batch_op.drop_column('restored_from')
        batch_op.drop_column('label')

