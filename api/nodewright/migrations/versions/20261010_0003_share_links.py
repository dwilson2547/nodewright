"""share links

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10 23:35:56.161232
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('share_links',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('canvas_id', sa.String(length=32), nullable=False),
    sa.Column('all_tabs', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['canvas_id'], ['canvases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token')
    )
    with op.batch_alter_table('share_links', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_share_links_canvas_id'), ['canvas_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('share_links', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_share_links_canvas_id'))

    op.drop_table('share_links')
