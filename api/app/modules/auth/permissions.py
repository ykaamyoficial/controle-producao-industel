USERS_VIEW = "users.view"
USERS_CREATE = "users.create"
USERS_UPDATE = "users.update"
USERS_DISABLE = "users.disable"
USERS_MANAGE_PERMISSIONS = "users.manage_permissions"
ROLES_VIEW = "roles.view"
ROLES_CREATE = "roles.create"
ROLES_UPDATE = "roles.update"
ROLES_MANAGE_PERMISSIONS = "roles.manage_permissions"
PERMISSIONS_VIEW = "permissions.view"
AUDIT_VIEW = "audit.view"
SYSTEM_ADMIN = "system.admin"
PROPOSALS_VIEW = "proposals.view"
PROPOSALS_CREATE = "proposals.create"
PROPOSALS_UPDATE = "proposals.update"
PROPOSALS_CANCEL = "proposals.cancel"
PROPOSALS_DELETE = "proposals.delete"
PROPOSALS_CHANGE_STATUS = "proposals.change_status"
PROPOSAL_ITEMS_VIEW = "proposal_items.view"
PROPOSAL_ITEMS_CREATE = "proposal_items.create"
PROPOSAL_ITEMS_UPDATE = "proposal_items.update"
PROPOSAL_ITEMS_DELETE = "proposal_items.delete"
PRODUCTION_VIEW = "production.view"
PRODUCTION_UPDATE = "production.update"
GALVANIZATION_VIEW = "galvanization.view"
GALVANIZATION_UPDATE = "galvanization.update"
EXPEDITION_VIEW = "expedition.view"
EXPEDITION_UPDATE = "expedition.update"
FISCAL_VIEW = "fiscal.view"
FISCAL_REGISTER_EMISSION = "fiscal.register_emission"
FISCAL_CANCEL_LINK = "fiscal.cancel_link"
CHAT_VIEW = "chat.view"
CHAT_SEND = "chat.send"
CHAT_VIEW_FINALIZED = "chat.view_finalized"
CHAT_ADMIN = "chat.admin"


OFFICIAL_PERMISSIONS = [
    (USERS_VIEW, "Visualizar usuarios", "users"),
    (USERS_CREATE, "Criar usuarios", "users"),
    (USERS_UPDATE, "Atualizar usuarios", "users"),
    (USERS_DISABLE, "Ativar ou desativar usuarios", "users"),
    (USERS_MANAGE_PERMISSIONS, "Gerenciar perfis de usuarios", "users"),
    (ROLES_VIEW, "Visualizar perfis", "roles"),
    (ROLES_CREATE, "Criar perfis", "roles"),
    (ROLES_UPDATE, "Atualizar perfis", "roles"),
    (ROLES_MANAGE_PERMISSIONS, "Gerenciar permissoes de perfis", "roles"),
    (PERMISSIONS_VIEW, "Visualizar permissoes", "roles"),
    (AUDIT_VIEW, "Visualizar auditoria de seguranca", "audit"),
    (SYSTEM_ADMIN, "Administrar API", "system"),
    (PROPOSALS_VIEW, "Visualizar propostas", "proposals"),
    (PROPOSALS_CREATE, "Criar propostas", "proposals"),
    (PROPOSALS_UPDATE, "Atualizar propostas", "proposals"),
    (PROPOSALS_CANCEL, "Cancelar propostas", "proposals"),
    (PROPOSALS_DELETE, "Desativar propostas", "proposals"),
    (PROPOSALS_CHANGE_STATUS, "Alterar status de propostas", "proposals"),
    (PROPOSAL_ITEMS_VIEW, "Visualizar itens de propostas", "proposals"),
    (PROPOSAL_ITEMS_CREATE, "Criar itens de propostas", "proposals"),
    (PROPOSAL_ITEMS_UPDATE, "Atualizar itens de propostas", "proposals"),
    (PROPOSAL_ITEMS_DELETE, "Remover itens de propostas", "proposals"),
    (PRODUCTION_VIEW, "Visualizar Producao", "production"),
    (PRODUCTION_UPDATE, "Alterar Producao", "production"),
    (GALVANIZATION_VIEW, "Visualizar Galvanizacao", "galvanization"),
    (GALVANIZATION_UPDATE, "Alterar Galvanizacao", "galvanization"),
    (EXPEDITION_VIEW, "Visualizar Expedicao", "expedition"),
    (EXPEDITION_UPDATE, "Alterar Expedicao", "expedition"),
    (FISCAL_VIEW, "Visualizar Fiscal", "fiscal"),
    (FISCAL_REGISTER_EMISSION, "Registrar emissao fiscal", "fiscal"),
    (FISCAL_CANCEL_LINK, "Cancelar vinculo fiscal interno", "fiscal"),
    (CHAT_VIEW, "Visualizar chats", "chat"),
    (CHAT_SEND, "Enviar mensagens no chat", "chat"),
    (CHAT_VIEW_FINALIZED, "Visualizar conversas finalizadas", "chat"),
    (CHAT_ADMIN, "Administrar modulo de chat", "chat"),
]


ADMIN_PERMISSION_CODES = [code for code, _name, _module in OFFICIAL_PERMISSIONS]
