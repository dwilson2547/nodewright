"""icon source

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11 01:46:31.578186
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('icons', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('icons', schema=None) as batch_op:
        batch_op.drop_column('source')

