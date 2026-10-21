"""Initial v1.2 PostgreSQL schema; frozen DDL, independent of future model changes."""

from alembic import op

revision = "0001_v12"
down_revision = None
branch_labels = depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE rate_limits (\n\tid VARCHAR(64) NOT NULL, \n\tcount INTEGER NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE users (\n\tid VARCHAR(80) NOT NULL, \n\temail VARCHAR(254) NOT NULL, \n\tdisplay_name VARCHAR(80) NOT NULL, \n\tpassword_salt BYTEA NOT NULL, \n\tpassword_hash BYTEA NOT NULL, \n\tsession_version INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT normalized_email CHECK (email = lower(trim(email))), \n\tUNIQUE (email)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE audit_logs (\n\tid VARCHAR(120) NOT NULL, \n\tuser_id VARCHAR(80) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tkind VARCHAR(80) NOT NULL, \n\tref_id VARCHAR(120) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE organizations (\n\tid VARCHAR(80) NOT NULL, \n\tuser_id VARCHAR(80) NOT NULL, \n\tmanager_agent_id VARCHAR(80) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tbusiness JSONB NOT NULL, \n\tplan JSONB NOT NULL, \n\tstatus VARCHAR(40) NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, id), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE sessions (\n\ttoken_hash VARCHAR(64) NOT NULL, \n\tuser_id VARCHAR(80) NOT NULL, \n\tcsrf VARCHAR(100) NOT NULL, \n\tsession_version INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (token_hash), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE departments (\n\tuser_id VARCHAR(80) NOT NULL, \n\torg_id VARCHAR(80) NOT NULL, \n\tid VARCHAR(80) NOT NULL, \n\tname VARCHAR(120) NOT NULL, \n\tconfig JSONB NOT NULL, \n\tPRIMARY KEY (user_id, org_id, id), \n\tFOREIGN KEY(user_id, org_id) REFERENCES organizations (user_id, id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE memberships (\n\torg_id VARCHAR(80) NOT NULL, \n\tuser_id VARCHAR(80) NOT NULL, \n\towner_id VARCHAR(80) NOT NULL, \n\trole VARCHAR(20) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (org_id, user_id), \n\tFOREIGN KEY(owner_id, org_id) REFERENCES organizations (user_id, id) ON DELETE CASCADE, \n\tCONSTRAINT membership_role CHECK (role IN ('owner','editor','viewer')), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE runs (\n\tmode VARCHAR(10) NOT NULL, \n\tstatus VARCHAR(40) NOT NULL, \n\toutputs JSONB NOT NULL, \n\tid VARCHAR(120) NOT NULL, \n\tuser_id VARCHAR(80) NOT NULL, \n\torg_id VARCHAR(80) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id, org_id) REFERENCES organizations (user_id, id) ON DELETE CASCADE, \n\tUNIQUE (user_id, org_id, id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE agents (\n\tuser_id VARCHAR(80) NOT NULL, \n\tid VARCHAR(80) NOT NULL, \n\torg_id VARCHAR(80), \n\tdepartment_id VARCHAR(80), \n\tcapability VARCHAR(80) NOT NULL, \n\trole VARCHAR(120) NOT NULL, \n\tconfig JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (user_id, id), \n\tUNIQUE (user_id, org_id, id), \n\tFOREIGN KEY(user_id, org_id) REFERENCES organizations (user_id, id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id, org_id, department_id) REFERENCES departments (user_id, org_id, id), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE conversations (\n\trun_id VARCHAR(80) NOT NULL, \n\tsender_id VARCHAR(80) NOT NULL, \n\treceiver_id VARCHAR(80) NOT NULL, \n\tcontent TEXT NOT NULL, \n\tid VARCHAR(120) NOT NULL, \n\tuser_id VARCHAR(80) NOT NULL, \n\torg_id VARCHAR(80) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id, org_id) REFERENCES organizations (user_id, id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id, org_id, run_id) REFERENCES runs (user_id, org_id, id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id, sender_id) REFERENCES agents (user_id, id), \n\tFOREIGN KEY(user_id, receiver_id) REFERENCES agents (user_id, id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE decisions (\n\tagent_id VARCHAR(80) NOT NULL, \n\trun_id VARCHAR(80), \n\tdata JSONB NOT NULL, \n\tid VARCHAR(120) NOT NULL, \n\tuser_id VARCHAR(80) NOT NULL, \n\torg_id VARCHAR(80) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id, org_id) REFERENCES organizations (user_id, id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id, agent_id) REFERENCES agents (user_id, id), \n\tFOREIGN KEY(user_id, org_id, run_id) REFERENCES runs (user_id, org_id, id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE feedback (\n\tagent_id VARCHAR(80), \n\tscore INTEGER, \n\tcapabilities JSONB NOT NULL, \n\tnotes TEXT NOT NULL, \n\tverified BOOLEAN NOT NULL, \n\tpolicy_version INTEGER NOT NULL, \n\tcorrected_strategy VARCHAR(20), \n\tid VARCHAR(120) NOT NULL, \n\tuser_id VARCHAR(80) NOT NULL, \n\torg_id VARCHAR(80) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id, org_id) REFERENCES organizations (user_id, id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id, org_id, agent_id) REFERENCES agents (user_id, org_id, id), \n\tCONSTRAINT feedback_score CHECK (score IS NULL OR score BETWEEN 1 AND 5)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE policies (\n\tuser_id VARCHAR(80) NOT NULL, \n\tpolicy_id VARCHAR(80) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tblob BYTEA NOT NULL, \n\tPRIMARY KEY (user_id, policy_id), \n\tFOREIGN KEY(user_id, policy_id) REFERENCES agents (user_id, id) ON DELETE CASCADE, \n\tCONSTRAINT policy_version_nonnegative CHECK (version >= 0)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE relationships (\n\tsource VARCHAR(80) NOT NULL, \n\ttarget VARCHAR(80) NOT NULL, \n\tkind VARCHAR(40) NOT NULL, \n\tid VARCHAR(120) NOT NULL, \n\tuser_id VARCHAR(80) NOT NULL, \n\torg_id VARCHAR(80) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id, org_id) REFERENCES organizations (user_id, id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id, source) REFERENCES agents (user_id, id), \n\tFOREIGN KEY(user_id, target) REFERENCES agents (user_id, id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE policy_versions (\n\tuser_id VARCHAR(80) NOT NULL, \n\tpolicy_id VARCHAR(80) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tblob BYTEA NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (user_id, policy_id, version), \n\tFOREIGN KEY(user_id, policy_id) REFERENCES policies (user_id, policy_id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute("CREATE INDEX ix_rate_limits_expires_at ON rate_limits (expires_at)")
    op.execute(
        "CREATE INDEX audit_owner_created ON audit_logs (user_id, created_at, id)"
    )
    op.execute(
        "ALTER TABLE organizations ADD CONSTRAINT organization_manager_owner FOREIGN KEY(user_id, manager_agent_id) REFERENCES agents (user_id, id)"
    )
    op.execute(
        "CREATE INDEX organizations_owner_created ON organizations (user_id, created_at, id)"
    )
    op.execute("CREATE INDEX ix_sessions_expires_at ON sessions (expires_at)")
    op.execute("CREATE INDEX ix_sessions_user_id ON sessions (user_id)")
    op.execute("CREATE INDEX memberships_owner_org ON memberships (owner_id, org_id)")
    op.execute("CREATE INDEX runs_owner_org ON runs (user_id, org_id, created_at, id)")
    op.execute("CREATE INDEX agents_owner_org ON agents (user_id, org_id, created_at)")
    op.execute(
        "CREATE INDEX conversations_owner_org ON conversations (user_id, org_id, created_at, id)"
    )
    op.execute(
        "CREATE INDEX decisions_owner_org ON decisions (user_id, org_id, created_at, id)"
    )
    op.execute(
        "CREATE INDEX feedback_owner_org ON feedback (user_id, org_id, created_at, id)"
    )
    op.execute(
        "CREATE INDEX relationships_owner_org ON relationships (user_id, org_id, created_at, id)"
    )


def downgrade():
    op.execute("DROP TABLE policy_versions CASCADE")
    op.execute("DROP TABLE relationships CASCADE")
    op.execute("DROP TABLE policies CASCADE")
    op.execute("DROP TABLE feedback CASCADE")
    op.execute("DROP TABLE decisions CASCADE")
    op.execute("DROP TABLE conversations CASCADE")
    op.execute("DROP TABLE agents CASCADE")
    op.execute("DROP TABLE runs CASCADE")
    op.execute("DROP TABLE memberships CASCADE")
    op.execute("DROP TABLE departments CASCADE")
    op.execute("DROP TABLE sessions CASCADE")
    op.execute("DROP TABLE organizations CASCADE")
    op.execute("DROP TABLE audit_logs CASCADE")
    op.execute("DROP TABLE users CASCADE")
    op.execute("DROP TABLE rate_limits CASCADE")
