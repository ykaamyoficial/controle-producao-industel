import { ClipboardList, Factory, Flame, Truck, Receipt, type LucideIcon } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { areasVisibleFor, type AreaKey } from '../areas/areaPermissionMap'
import { useAuth } from '../auth/AuthContext'

const AREA_ICONS: Record<AreaKey, LucideIcon> = {
  proposals: ClipboardList,
  production: Factory,
  galvanization: Flame,
  expedition: Truck,
  fiscal: Receipt,
}

export function BottomNav() {
  const { user } = useAuth()
  const areas = areasVisibleFor(user?.permissions ?? [])

  if (areas.length === 0) return null

  return (
    <nav className="fixed inset-x-0 bottom-0 flex justify-around border-t border-slate-800 bg-slate-950/95 py-1.5 backdrop-blur">
      {areas.map((area) => {
        const Icon = AREA_ICONS[area.key]
        return (
          <NavLink
            key={area.key}
            to={area.route}
            end={area.route === '/'}
            className={({ isActive }) =>
              `flex min-w-16 flex-col items-center gap-0.5 rounded-lg px-3 py-1.5 text-xs ${
                isActive ? 'text-sky-400' : 'text-slate-400'
              }`
            }
          >
            <Icon size={22} strokeWidth={2} />
            <span>{area.label}</span>
          </NavLink>
        )
      })}
    </nav>
  )
}
