"""orgs: organisations, their members, and workspaces owned by an org (design §19)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-12 01:24:11.479855
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('orgs',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('org_members',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('org_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'user_id')
    )
    with op.batch_alter_table('org_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_org_members_org_id'), ['org_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_org_members_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.add_column(sa.Column('org_id', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('org_access', sa.String(length=16), server_default='editor', nullable=False))
        batch_op.create_index(batch_op.f('ix_workspaces_org_id'), ['org_id'], unique=False)
        batch_op.create_foreign_key('fk_workspaces_org_id', 'orgs', ['org_id'], ['id'], ondelete='RESTRICT')



def downgrade() -> None:
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.drop_constraint('fk_workspaces_org_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_workspaces_org_id'))
        batch_op.drop_column('org_access')
        batch_op.drop_column('org_id')

    with op.batch_alter_table('org_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_org_members_user_id'))
        batch_op.drop_index(batch_op.f('ix_org_members_org_id'))

    op.drop_table('org_members')
    op.drop_table('orgs')
