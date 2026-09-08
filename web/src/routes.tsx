import { Navigate, Route, Routes } from 'react-router-dom'
import { BottomNav } from './components/BottomNav'
import { useAuth } from './auth/AuthContext'
import { ControlGeneralPage } from './pages/ControlGeneralPage'
import { ExpeditionAreaPage } from './pages/ExpeditionAreaPage'
import { FiscalAreaPage } from './pages/FiscalAreaPage'
import { FiscalDetailPage } from './pages/FiscalDetailPage'
import { GalvanizationAreaPage } from './pages/GalvanizationAreaPage'
import { LoginPage } from './pages/LoginPage'
import { ProductionAreaPage } from './pages/ProductionAreaPage'
import { ProposalDetailPage } from './pages/ProposalDetailPage'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <div className="flex min-h-svh flex-col bg-slate-950 text-slate-100">
              <Routes>
                <Route path="/" element={<ControlGeneralPage />} />
                <Route path="/propostas/:id" element={<ProposalDetailPage />} />
                <Route path="/producao" element={<ProductionAreaPage />} />
                <Route path="/galvanizacao" element={<GalvanizationAreaPage />} />
                <Route path="/expedicao" element={<ExpeditionAreaPage />} />
                <Route path="/fiscal" element={<FiscalAreaPage />} />
                <Route path="/fiscal/:id" element={<FiscalDetailPage />} />
              </Routes>
              <BottomNav />
            </div>
          </RequireAuth>
        }
      />
    </Routes>
  )
}
