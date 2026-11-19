"""sicaad access model

Revision: e643effaab58
Down revision: b9101686b897
Date: 2026-11-10 16:35:22.117578

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers used by Alembic to track history
revision: str = 'e643effaab58'
down_revision: Union[str, None] = 'b9101686b897'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UQ_USER_MENU = 'uq_user_menu_accesses_user_menu'
FK_ACCESS_LEVEL = 'fk_user_menu_accesses_access_level_id'


def upgrade() -> None:
    """Apply the schema changes."""
    # The old grants referenced the legacy enum model; clear them so we can add
    # the NOT NULL access_level_id FK. The seed re-creates the admin grants.
    op.execute('DELETE FROM user_menu_accesses')

    # New access levels catalog
    op.create_table(
        'access_levels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_access_levels_id'), 'access_levels', ['id'], unique=False)
    op.create_index(op.f('ix_access_levels_key'), 'access_levels', ['key'], unique=True)

    # menus: new fields, drop the legacy role column
    op.add_column('menus', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('menus', sa.Column('has_access_levels', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.drop_constraint(op.f('menus_user_type_id_fkey'), 'menus', type_='foreignkey')
    op.drop_column('menus', 'user_type_id')

    # user_menu_accesses: level now lives here (FK), plus soft-delete + timestamps
    op.drop_column('user_menu_accesses', 'access_level')
    op.add_column('user_menu_accesses', sa.Column('access_level_id', sa.Integer(), nullable=False))
    op.add_column('user_menu_accesses', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('user_menu_accesses', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('user_menu_accesses', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.create_index(op.f('ix_user_menu_accesses_access_level_id'), 'user_menu_accesses', ['access_level_id'], unique=False)
    op.create_unique_constraint(UQ_USER_MENU, 'user_menu_accesses', ['user_id', 'menu_id'])
    op.create_foreign_key(FK_ACCESS_LEVEL, 'user_menu_accesses', 'access_levels', ['access_level_id'], ['id'])

    # users: drop the legacy role column
    op.drop_constraint(op.f('users_user_type_id_fkey'), 'users', type_='foreignkey')
    op.drop_column('users', 'user_type_id')

    # Finally drop the roles table (no FKs reference it anymore)
    op.drop_index(op.f('ix_user_types_id'), table_name='user_types')
    op.drop_table('user_types')


def downgrade() -> None:
    """Revert the changes applied in upgrade()."""
    op.create_table(
        'user_types',
        sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('name', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('description', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('user_types_pkey')),
        sa.UniqueConstraint('name', name=op.f('user_types_name_key')),
    )
    op.create_index(op.f('ix_user_types_id'), 'user_types', ['id'], unique=False)

    op.add_column('users', sa.Column('user_type_id', sa.INTEGER(), autoincrement=False, nullable=True))
    op.create_foreign_key(op.f('users_user_type_id_fkey'), 'users', 'user_types', ['user_type_id'], ['id'])

    op.drop_constraint(FK_ACCESS_LEVEL, 'user_menu_accesses', type_='foreignkey')
    op.drop_constraint(UQ_USER_MENU, 'user_menu_accesses', type_='unique')
    op.drop_index(op.f('ix_user_menu_accesses_access_level_id'), table_name='user_menu_accesses')
    op.drop_column('user_menu_accesses', 'updated_at')
    op.drop_column('user_menu_accesses', 'created_at')
    op.drop_column('user_menu_accesses', 'is_active')
    op.drop_column('user_menu_accesses', 'access_level_id')
    op.add_column(
        'user_menu_accesses',
        sa.Column(
            'access_level',
            postgresql.ENUM('capturista', 'administrator', 'super_admin', name='access_level_enum'),
            autoincrement=False,
            nullable=True,
        ),
    )

    op.add_column('menus', sa.Column('user_type_id', sa.INTEGER(), autoincrement=False, nullable=True))
    op.create_foreign_key(op.f('menus_user_type_id_fkey'), 'menus', 'user_types', ['user_type_id'], ['id'])
    op.drop_column('menus', 'has_access_levels')
    op.drop_column('menus', 'description')

    op.drop_index(op.f('ix_access_levels_key'), table_name='access_levels')
    op.drop_index(op.f('ix_access_levels_id'), table_name='access_levels')
    op.drop_table('access_levels')
