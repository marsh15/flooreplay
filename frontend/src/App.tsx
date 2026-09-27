import { Route, Routes } from 'react-router'

import { HomePage } from '@/pages/Home'
import { WorkbenchPage } from '@/pages/Workbench'

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/workbench" element={<WorkbenchPage />} />
    </Routes>
  )
}

export default App
