import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { PageHeader } from '@/components/board'

export function NotFoundPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Page not found">
        <p className="mt-2 max-w-2xl text-base text-muted-foreground">
          This address does not match an order, investigation, report or tool in FloorReplay. Check
          the link, or start from the order decisions page.
        </p>
      </PageHeader>
      <Button asChild>
        <Link to="/">Open order decisions</Link>
      </Button>
    </div>
  )
}
