from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)


agent_read_metadata = MetaData()

agent_inspection_read = Table(
    "ai_inspection_read",
    agent_read_metadata,
    Column("inspection_id", BigInteger, primary_key=True),
    Column("company_id", BigInteger, nullable=False),
    Column("category_id", BigInteger, nullable=False),
    Column("uid", BigInteger),
    Column("name", String(100), nullable=False),
    Column("location", String(250), nullable=False),
    Column("cycle", String(50), nullable=False),
    Column("content", Text),
)

agent_inspection_history_read = Table(
    "ai_inspection_history_read",
    agent_read_metadata,
    Column("inspection_history_id", BigInteger, primary_key=True),
    Column("company_id", BigInteger, nullable=False),
    Column("inspection_id", BigInteger, nullable=False),
    Column("uid", BigInteger),
    Column("user_name", String(100)),
    Column("name", String(100), nullable=False),
    Column("location", String(50), nullable=False),
    Column("date", DateTime, nullable=False),
    Column("status", String(50), nullable=False),
    Column("is_action_required", Boolean, nullable=False),
    Column("content", Text),
)

agent_action_history_read = Table(
    "ai_action_history_read",
    agent_read_metadata,
    Column("action_history_id", BigInteger, primary_key=True),
    Column("company_id", BigInteger, nullable=False),
    Column("inspection_history_id", BigInteger),
    Column("category_id", BigInteger, nullable=False),
    Column("handler_uid", BigInteger),
    Column("handler_name", String(100)),
    Column("approver_uid", BigInteger),
    Column("approver_name", String(100)),
    Column("action_name", String(200), nullable=False),
    Column("source_type", String(50), nullable=False),
    Column("source_id", BigInteger),
    Column("location", String(255), nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("completed_at", DateTime),
    Column("action_status", String(50), nullable=False),
    Column("content", Text, nullable=False),
    Column("approval_status", String(50)),
    Column("approval_date", DateTime),
    Column("rejection_reason", Text),
)

agent_event_category_read = Table(
    "ai_event_category_read",
    agent_read_metadata,
    Column("category_id", BigInteger, primary_key=True),
    Column("company_id", BigInteger, nullable=False),
    Column("category", String(50), nullable=False),
    Column("category_name", String(100), nullable=False),
    Column("level", Integer, nullable=False),
)

agent_user_display_read = Table(
    "ai_user_display_read",
    agent_read_metadata,
    Column("uid", BigInteger, primary_key=True),
    Column("company_id", BigInteger, nullable=False),
    Column("name", String(100), nullable=False),
    Column("role", String(50), nullable=False),
)

agent_education_read = Table(
    "ai_education_read",
    agent_read_metadata,
    Column("education_id", BigInteger, primary_key=True),
    Column("company_id", BigInteger, nullable=False),
    Column("title", String(200), nullable=False),
    Column("video_url", String(500), nullable=False),
    Column("category", String(100), nullable=False),
    Column("education_type", String(50), nullable=False),
    Column("due_date", Date),
)

agent_education_status_read = Table(
    "ai_education_status_read",
    agent_read_metadata,
    Column("uid", BigInteger, primary_key=True),
    Column("education_id", BigInteger, primary_key=True),
    Column("company_id", BigInteger, nullable=False),
    Column("user_name", String(100)),
    Column("status", String(20), nullable=False),
    Column("completed_date", Date),
)

agent_education_user_read = Table(
    "ai_education_user_read",
    agent_read_metadata,
    Column("uid", BigInteger, primary_key=True),
    Column("company_id", BigInteger, nullable=False),
    Column("name", String(100), nullable=False),
    Column("role", String(50), nullable=False),
    Column("category", String(100)),
)
