import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router'

import { AppShell } from '@/components/AppShell'
const IncidentDemoPage = lazy(() => import('@/pages/IncidentDemo').then((module) => ({ default: module.IncidentDemoPage })))
const ComparisonPage = lazy(() => import('@/pages/Comparison').then((module) => ({ default: module.ComparisonPage })))
const ImportsPage = lazy(() => import('@/pages/Imports').then((module) => ({ default: module.ImportsPage })))
const NotesPage = lazy(() => import('@/pages/Notes').then((module) => ({ default: module.NotesPage })))
const LibraryPage = lazy(() => import('@/pages/Library').then((module) => ({ default: module.LibraryPage })))
const WorkbenchPage = lazy(() => import('@/pages/Workbench').then((module) => ({ default: module.WorkbenchPage })))
const IncidentLibraryPage = lazy(() => import('@/pages/IncidentLibrary').then((module) => ({ default: module.IncidentLibraryPage })))
const IncidentWorkbenchPage = lazy(() => import('@/pages/IncidentWorkbench').then((module) => ({ default: module.IncidentWorkbenchPage })))
const IncidentEvaluationPage = lazy(() => import('@/pages/IncidentEvaluation').then((module) => ({ default: module.IncidentEvaluationPage })))
const IncidentImportsPage = lazy(() => import('@/pages/IncidentImports').then((module) => ({ default: module.IncidentImportsPage })))

function App() {
  return (
    <AppShell>
      <Suspense fallback={<p role="status">Loading page…</p>}><Routes>
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
      </Routes></Suspense>
    </AppShell>
  )
}

export default App
