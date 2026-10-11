"""folders

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-10 23:28:10.347732
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('folders',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('parent_id', sa.String(length=32), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_id'], ['folders.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_folders_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_folders_parent_id'), ['parent_id'], unique=False)

    op.create_table('workspace_folders',
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('workspace_id', sa.String(length=32), nullable=False),
    sa.Column('folder_id', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['folder_id'], ['folders.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'workspace_id')
    )
    with op.batch_alter_table('workspace_folders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workspace_folders_folder_id'), ['folder_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('workspace_folders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workspace_folders_folder_id'))

    op.drop_table('workspace_folders')
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_folders_parent_id'))
        batch_op.drop_index(batch_op.f('ix_folders_owner_id'))

    op.drop_table('folders')
