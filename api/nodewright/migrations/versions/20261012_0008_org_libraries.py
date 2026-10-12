"""org libraries: templates and icons shared with an org, and org style guides (design §20)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-12 01:44:54.479523
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('org_style_guides',
    sa.Column('org_id', sa.String(length=32), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('org_id')
    )
    with op.batch_alter_table('icons', schema=None) as batch_op:
        batch_op.add_column(sa.Column('org_id', sa.String(length=32), nullable=True))
        batch_op.create_index(batch_op.f('ix_icons_org_id'), ['org_id'], unique=False)
        batch_op.create_foreign_key('fk_icons_org_id', 'orgs', ['org_id'], ['id'], ondelete='CASCADE')

    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('org_id', sa.String(length=32), nullable=True))
        batch_op.create_index(batch_op.f('ix_templates_org_id'), ['org_id'], unique=False)
        batch_op.create_foreign_key('fk_templates_org_id', 'orgs', ['org_id'], ['id'], ondelete='CASCADE')



def downgrade() -> None:
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.drop_constraint('fk_templates_org_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_templates_org_id'))
        batch_op.drop_column('org_id')

    with op.batch_alter_table('icons', schema=None) as batch_op:
        batch_op.drop_constraint('fk_icons_org_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_icons_org_id'))
        batch_op.drop_column('org_id')

    op.drop_table('org_style_guides')
