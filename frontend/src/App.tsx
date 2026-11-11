import { lazy, Suspense } from 'react'
import { Route, Routes, useLocation } from 'react-router'

import { AppShell } from '@/components/AppShell'
import { useAuth } from '@/components/Auth'
import { NavigationEffects } from '@/components/NavigationEffects'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { NotFoundPage } from '@/pages/NotFound'
const IncidentDemoPage = lazy(() =>
  import('@/pages/IncidentDemo').then((module) => ({ default: module.IncidentDemoPage })),
)
const ComparisonPage = lazy(() =>
  import('@/pages/Comparison').then((module) => ({ default: module.ComparisonPage })),
)
const ImportsPage = lazy(() =>
  import('@/pages/Imports').then((module) => ({ default: module.ImportsPage })),
)
const NotesPage = lazy(() =>
  import('@/pages/Notes').then((module) => ({ default: module.NotesPage })),
)
const LibraryPage = lazy(() =>
  import('@/pages/Library').then((module) => ({ default: module.LibraryPage })),
)
const WorkbenchPage = lazy(() =>
  import('@/pages/Workbench').then((module) => ({ default: module.WorkbenchPage })),
)
const IncidentLibraryPage = lazy(() =>
  import('@/pages/IncidentLibrary').then((module) => ({ default: module.IncidentLibraryPage })),
)
const IncidentWorkbenchPage = lazy(() =>
  import('@/pages/IncidentWorkbench').then((module) => ({ default: module.IncidentWorkbenchPage })),
)
const IncidentEvaluationPage = lazy(() =>
  import('@/pages/IncidentEvaluation').then((module) => ({
    default: module.IncidentEvaluationPage,
  })),
)
const IncidentImportsPage = lazy(() =>
  import('@/pages/IncidentImports').then((module) => ({ default: module.IncidentImportsPage })),
)
const DecisionsHomePage = lazy(() =>
  import('@/pages/decisions/DecisionsHome').then((module) => ({ default: module.DecisionsHome })),
)
const OrderDecisionPage = lazy(() =>
  import('@/pages/decisions/OrderDecision').then((module) => ({ default: module.OrderDecision })),
)
const TimelinePage = lazy(() =>
  import('@/pages/decisions/Timeline').then((module) => ({ default: module.Timeline })),
)
const ReplayLabPage = lazy(() =>
  import('@/pages/decisions/ReplayLab').then((module) => ({ default: module.ReplayLab })),
)
const ReviewQueuePage = lazy(() =>
  import('@/pages/decisions/ReviewQueue').then((module) => ({ default: module.ReviewQueue })),
)
const DecisionImportsPage = lazy(() =>
  import('@/pages/decisions/DecisionImports').then((module) => ({
    default: module.DecisionImports,
  })),
)

const OperationsPage = lazy(() =>
  import('@/pages/Operations').then((module) => ({ default: module.OperationsPage })),
)
const WorkspacesPage = lazy(() =>
  import('@/pages/Workspaces').then((module) => ({ default: module.WorkspacesPage })),
)

function App() {
  const { pathname } = useLocation()
  const { user, epoch } = useAuth()
  return (
    <AppShell>
      <NavigationEffects />
      {/* Reset a failed screen on navigation and on every sign-in, sign-out or expiry. */}
      <ErrorBoundary key={`${user?.id ?? 'public'}:${epoch}:${pathname}`}>
        <Suspense
          fallback={
            <p role="status" className="text-sm text-muted-foreground">
              Loading page…
            </p>
          }
        >
          <Routes>
            <Route path="/operations" element={<OperationsPage />} />
            <Route path="/workspaces" element={<WorkspacesPage />} />
            <Route path="/" element={<DecisionsHomePage />} />
            <Route path="/orders/:orderId/timeline" element={<TimelinePage />} />
            <Route path="/orders/:orderId" element={<OrderDecisionPage />} />
            <Route path="/lab" element={<ReplayLabPage />} />
            <Route path="/review" element={<ReviewQueuePage />} />
            <Route path="/imports" element={<DecisionImportsPage />} />
            <Route path="/investigations" element={<IncidentLibraryPage />} />
            <Route path="/demo" element={<IncidentDemoPage />} />
            <Route path="/incidents/imports" element={<IncidentImportsPage />} />
            <Route path="/incidents/:id" element={<IncidentWorkbenchPage />} />
            <Route path="/evaluation" element={<IncidentEvaluationPage />} />
            <Route path="/coverage" element={<LibraryPage />} />
            <Route path="/coverage/workbench" element={<WorkbenchPage />} />
            <Route path="/coverage/notes" element={<NotesPage />} />
            <Route path="/coverage/imports" element={<ImportsPage />} />
            <Route path="/coverage/comparison" element={<ComparisonPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </AppShell>
  )
}

export default App
