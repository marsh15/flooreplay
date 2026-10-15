import { lazy, Suspense } from 'react'
import { Route, Routes, useLocation } from 'react-router'

import { AppShell } from '@/components/AppShell'
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

const OperationsPage = lazy(() =>
  import('@/pages/Operations').then((module) => ({ default: module.OperationsPage })),
)
const WorkspacesPage = lazy(() =>
  import('@/pages/Workspaces').then((module) => ({ default: module.WorkspacesPage })),
)

function App() {
  const { pathname } = useLocation()
  return (
    <AppShell>
      <ErrorBoundary key={pathname}>
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
            <Route path="/" element={<IncidentLibraryPage />} />
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
