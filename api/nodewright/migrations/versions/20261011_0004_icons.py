"""icons

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11 01:16:14.941605
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('icons',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('svg', sa.Text(), nullable=False),
    sa.Column('tinted', sa.Boolean(), nullable=False),
    sa.Column('ports', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('icons', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_icons_owner_id'), ['owner_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('icons', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_icons_owner_id'))

    op.drop_table('icons')
