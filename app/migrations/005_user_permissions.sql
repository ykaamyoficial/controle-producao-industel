CREATE TABLE IF NOT EXISTS usuario_permissoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    area_key TEXT NOT NULL,
    access_level TEXT NOT NULL CHECK(access_level IN ('NONE', 'VIEW', 'EDIT')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
    UNIQUE(usuario_id, area_key)
);

CREATE INDEX IF NOT EXISTS idx_usuario_permissoes_usuario
    ON usuario_permissoes(usuario_id);

CREATE INDEX IF NOT EXISTS idx_usuario_permissoes_area
    ON usuario_permissoes(area_key);

WITH areas(area_key) AS (
    VALUES
        ('dashboard'),
        ('executive_dashboard'),
        ('control_general'),
        ('production'),
        ('galvanization'),
        ('expedition'),
        ('fiscal'),
        ('partials'),
        ('warehouse'),
        ('operational_reports'),
        ('history'),
        ('settings'),
        ('users_permissions')
),
legacy_permissions AS (
    SELECT
        u.id AS usuario_id,
        a.area_key,
        CASE
            WHEN u.perfil = 'admin' AND COALESCE(u.ativo, 0) = 1 THEN 'EDIT'
            WHEN a.area_key = 'control_general'
                 AND instr(',' || upper(COALESCE(u.areas_acesso, '')) || ',', ',CONTROLE GERAL,') > 0 THEN 'EDIT'
            WHEN a.area_key = 'production'
                 AND instr(',' || upper(COALESCE(u.areas_acesso, '')) || ',', ',PRODUCAO,') > 0 THEN 'EDIT'
            WHEN a.area_key = 'galvanization'
                 AND instr(',' || upper(COALESCE(u.areas_acesso, '')) || ',', ',GALVANIZACAO,') > 0 THEN 'EDIT'
            WHEN a.area_key = 'expedition'
                 AND instr(',' || upper(COALESCE(u.areas_acesso, '')) || ',', ',EXPEDICAO,') > 0 THEN 'EDIT'
            WHEN a.area_key = 'warehouse'
                 AND instr(',' || upper(COALESCE(u.areas_acesso, '')) || ',', ',ALMOXARIFADO,') > 0 THEN 'EDIT'
            WHEN a.area_key = 'fiscal' AND u.perfil = 'fiscal' THEN 'EDIT'
            ELSE 'NONE'
        END AS access_level
    FROM usuarios u
    CROSS JOIN areas a
)
INSERT OR IGNORE INTO usuario_permissoes(usuario_id, area_key, access_level, created_at, updated_at)
SELECT usuario_id, area_key, access_level, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM legacy_permissions;
