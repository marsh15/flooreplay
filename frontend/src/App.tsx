import { Route, Routes } from 'react-router'

import { AppShell } from '@/components/AppShell'
import { ImportsPage } from '@/pages/Imports'
import { LibraryPage } from '@/pages/Library'
import { WorkbenchPage } from '@/pages/Workbench'

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<LibraryPage />} />
        <Route path="/workbench" element={<WorkbenchPage />} />
        <Route path="/imports" element={<ImportsPage />} />
      </Routes>
    </AppShell>
  )
}

export default App
