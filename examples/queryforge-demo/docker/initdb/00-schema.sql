-- Схема users: совпадает с app.models.User (документация: не менять без правок в ORM).
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    age INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ NULL,
    deleted_by VARCHAR(64) NULL,
    delete_reason VARCHAR(512) NULL
);

CREATE INDEX IF NOT EXISTS ix_users_deleted_at ON users (deleted_at);
CREATE INDEX IF NOT EXISTS ix_users_deleted_by ON users (deleted_by);
