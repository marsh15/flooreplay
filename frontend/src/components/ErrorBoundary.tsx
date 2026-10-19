import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { PageHeader, Limits } from '@/components/board'

interface State {
  error: Error | null
}

/** Catches render failures so one broken screen never blanks the whole shell. */
export class ErrorBoundary extends Component<{ children: ReactNode; fullPage?: boolean }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Screen failed to render', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    const fallback = (
      <div role="alert" className="space-y-6">
        <PageHeader title="This screen could not be shown">
          <p className="mt-2 max-w-2xl text-base text-muted-foreground">
            Something failed while drawing this page. Saved reports and source records are not
            changed by this error.
          </p>
        </PageHeader>
        <Limits tone="danger">{this.state.error.message}</Limits>
        <div className="flex flex-wrap gap-3">
          <Button onClick={() => window.location.reload()}>Reload page</Button>
          <Button asChild variant="outline">
            <Link to="/">Back to incidents</Link>
          </Button>
        </div>
      </div>
    )
    // Outside the app shell (a failure in the shell itself), supply the page frame.
    return this.props.fullPage ? (
      <main className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 lg:px-8">{fallback}</main>
    ) : (
      fallback
    )
  }
}
