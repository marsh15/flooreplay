import { Route, Routes } from 'react-router'

import { AppShell } from '@/components/AppShell'
import { LibraryPage } from '@/pages/Library'
import { WorkbenchPage } from '@/pages/Workbench'

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<LibraryPage />} />
        <Route path="/workbench" element={<WorkbenchPage />} />
      </Routes>
    </AppShell>
  )
}

export default App
