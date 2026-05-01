-- Демо-данные с фиксированными UUID для примеров в README.
INSERT INTO users (id, email, age, status, created_at)
VALUES
    (
        '11111111-1111-1111-1111-111111111101',
        'alice@example.com',
        28,
        'active',
        '2024-01-15T10:00:00+00:00'
    ),
    (
        '11111111-1111-1111-1111-111111111102',
        'bob@example.com',
        34,
        'active',
        '2024-02-20T12:30:00+00:00'
    ),
    (
        '11111111-1111-1111-1111-111111111103',
        'carol@example.com',
        22,
        'blocked',
        '2024-03-01T08:00:00+00:00'
    )
ON CONFLICT (id) DO NOTHING;
