export type AreaKey = 'production' | 'galvanization' | 'expedition' | 'fiscal' | 'proposals'

export interface AreaDefinition {
  key: AreaKey
  label: string
  /** permissions.module value returned by /auth/me */
  permissionModule: string
  viewPermission: string
  registerPermission: string | null
  route: string
}

export const AREA_DEFINITIONS: AreaDefinition[] = [
  {
    key: 'proposals',
    label: 'Controle Geral',
    permissionModule: 'proposals',
    viewPermission: 'proposals.view',
    registerPermission: 'proposals.change_status',
    route: '/',
  },
  {
    key: 'production',
    label: 'Producao',
    permissionModule: 'production',
    viewPermission: 'production.view',
    registerPermission: 'production.update',
    route: '/producao',
  },
  {
    key: 'galvanization',
    label: 'Galvanizacao',
    permissionModule: 'galvanization',
    viewPermission: 'galvanization.view',
    registerPermission: 'galvanization.update',
    route: '/galvanizacao',
  },
  {
    key: 'expedition',
    label: 'Expedicao',
    permissionModule: 'expedition',
    viewPermission: 'expedition.view',
    registerPermission: 'expedition.update',
    route: '/expedicao',
  },
  {
    key: 'fiscal',
    label: 'Fiscal',
    permissionModule: 'fiscal',
    viewPermission: 'fiscal.view',
    registerPermission: 'fiscal.register_emission',
    route: '/fiscal',
  },
]

function hasPermission(permissions: string[], required: string): boolean {
  return permissions.includes('*') || permissions.includes(required)
}

export function areasVisibleFor(permissions: string[]): AreaDefinition[] {
  return AREA_DEFINITIONS.filter((area) => hasPermission(permissions, area.viewPermission))
}

export function canRegisterIn(area: AreaDefinition, permissions: string[]): boolean {
  if (!area.registerPermission) return false
  return hasPermission(permissions, area.registerPermission)
}
