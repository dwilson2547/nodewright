"""baseline: schema as of 0.6.0

Revision ID: 0001
Revises:
Create Date: 2026-10-10 23:26:36.337256
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('oauth_clients',
    sa.Column('client_id', sa.String(length=64), nullable=False),
    sa.Column('info', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('client_id')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=True)

    op.create_table('access_tokens',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('prefix', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('access_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_access_tokens_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_access_tokens_user_id'), ['user_id'], unique=False)

    op.create_table('oauth_codes',
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('client_id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['oauth_clients.client_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('code_hash')
    )
    op.create_table('oauth_grants',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('client_id', sa.String(length=64), nullable=False),
    sa.Column('client_name', sa.String(length=100), nullable=False),
    sa.Column('scopes', sa.String(length=200), nullable=False),
    sa.Column('resource', sa.String(length=300), nullable=True),
    sa.Column('access_hash', sa.String(length=64), nullable=False),
    sa.Column('access_expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('refresh_hash', sa.String(length=64), nullable=False),
    sa.Column('refresh_expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['oauth_clients.client_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('oauth_grants', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_oauth_grants_access_hash'), ['access_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_oauth_grants_client_id'), ['client_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_oauth_grants_refresh_hash'), ['refresh_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_oauth_grants_user_id'), ['user_id'], unique=False)

    op.create_table('oauth_requests',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('client_id', sa.String(length=64), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=True),
    sa.Column('nonce', sa.String(length=64), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['oauth_clients.client_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('session_tokens',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash')
    )
    with op.batch_alter_table('session_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_session_tokens_user_id'), ['user_id'], unique=False)

    op.create_table('style_guides',
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('templates',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_templates_owner_id'), ['owner_id'], unique=False)

    op.create_table('user_identities',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('issuer', sa.String(length=255), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('issuer', 'subject')
    )
    with op.batch_alter_table('user_identities', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_identities_user_id'), ['user_id'], unique=False)

    op.create_table('user_prefs',
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('default_page', sa.String(length=64), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('workspaces',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workspaces_owner_id'), ['owner_id'], unique=False)

    op.create_table('attachments',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('workspace_id', sa.String(length=32), nullable=False),
    sa.Column('uploader_id', sa.String(length=32), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['uploader_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_attachments_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('canvases',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('workspace_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('canvases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_canvases_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('workspace_members',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('workspace_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'user_id')
    )
    with op.batch_alter_table('workspace_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workspace_members_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspace_members_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('canvas_leases',
    sa.Column('canvas_id', sa.String(length=32), nullable=False),
    sa.Column('holder', sa.String(length=128), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['canvas_id'], ['canvases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('canvas_id')
    )
    op.create_table('canvas_revisions',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('canvas_id', sa.String(length=32), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['canvas_id'], ['canvases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('canvas_id', 'revision')
    )
    with op.batch_alter_table('canvas_revisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_canvas_revisions_canvas_id'), ['canvas_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('canvas_revisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_canvas_revisions_canvas_id'))

    op.drop_table('canvas_revisions')
    op.drop_table('canvas_leases')
    with op.batch_alter_table('workspace_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workspace_members_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_workspace_members_user_id'))

    op.drop_table('workspace_members')
    with op.batch_alter_table('canvases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_canvases_workspace_id'))

    op.drop_table('canvases')
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_attachments_workspace_id'))

    op.drop_table('attachments')
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workspaces_owner_id'))

    op.drop_table('workspaces')
    op.drop_table('user_prefs')
    with op.batch_alter_table('user_identities', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_identities_user_id'))

    op.drop_table('user_identities')
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_templates_owner_id'))

    op.drop_table('templates')
    op.drop_table('style_guides')
    with op.batch_alter_table('session_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_session_tokens_user_id'))

    op.drop_table('session_tokens')
    op.drop_table('oauth_requests')
    with op.batch_alter_table('oauth_grants', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_oauth_grants_user_id'))
        batch_op.drop_index(batch_op.f('ix_oauth_grants_refresh_hash'))
        batch_op.drop_index(batch_op.f('ix_oauth_grants_client_id'))
        batch_op.drop_index(batch_op.f('ix_oauth_grants_access_hash'))

    op.drop_table('oauth_grants')
    op.drop_table('oauth_codes')
    with op.batch_alter_table('access_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_access_tokens_user_id'))
        batch_op.drop_index(batch_op.f('ix_access_tokens_token_hash'))

    op.drop_table('access_tokens')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_username'))

    op.drop_table('users')
    op.drop_table('oauth_clients')
