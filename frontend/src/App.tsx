import { Route, Routes } from 'react-router'

import { AppShell } from '@/components/AppShell'
import { ComparisonPage } from '@/pages/Comparison'
import { ImportsPage } from '@/pages/Imports'
import { NotesPage } from '@/pages/Notes'
import { LibraryPage } from '@/pages/Library'
import { WorkbenchPage } from '@/pages/Workbench'
import { IncidentLibraryPage } from '@/pages/IncidentLibrary'
import { IncidentWorkbenchPage } from '@/pages/IncidentWorkbench'
import { IncidentEvaluationPage } from '@/pages/IncidentEvaluation'
import { IncidentImportsPage } from '@/pages/IncidentImports'

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<IncidentLibraryPage />} />
        <Route path="/incidents/imports" element={<IncidentImportsPage />} />
        <Route path="/incidents/:id" element={<IncidentWorkbenchPage />} />
        <Route path="/evaluation" element={<IncidentEvaluationPage />} />
        <Route path="/coverage" element={<LibraryPage />} />
        <Route path="/coverage/workbench" element={<WorkbenchPage />} />
        <Route path="/coverage/notes" element={<NotesPage />} />
        <Route path="/coverage/imports" element={<ImportsPage />} />
        <Route path="/coverage/comparison" element={<ComparisonPage />} />
      </Routes>
    </AppShell>
  )
}

export default App
