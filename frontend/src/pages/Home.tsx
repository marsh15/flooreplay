import { Link } from 'react-router'

import { Button } from '@/components/ui/button'

export function HomePage() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-3xl font-semibold tracking-tight">Flooreplay</h1>
      <p className="max-w-md text-center text-muted-foreground">
        Placeholder home page. The scaffold is ready — replace this with the
        real UI.
      </p>
      <Button asChild>
        <Link to="/workbench">Open workbench</Link>
      </Button>
    </main>
  )
}
