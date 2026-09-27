import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'

export function WorkbenchPage() {
  return (
    <main className="flex min-h-svh items-center justify-center p-8">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle>Workbench</CardTitle>
            <Badge variant="secondary">placeholder</Badge>
          </div>
          <CardDescription>
            Placeholder page for the <code className="font-mono">/workbench</code>{' '}
            route.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Separator className="mb-4" />
          <p className="font-mono text-sm text-muted-foreground">
            Replace this with the workbench UI.
          </p>
        </CardContent>
      </Card>
    </main>
  )
}
