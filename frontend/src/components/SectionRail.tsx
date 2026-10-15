import { useEffect, useState } from 'react'
import { sectionId } from '@/components/board'
import { cn } from '@/lib/utils'

/** Sticky in-page navigation. The active section follows the scroll position. */
export function SectionRail({ titles }: { titles: readonly string[] }) {
  const [active, setActive] = useState<string | null>(null)
  useEffect(() => {
    let frame = 0
    const update = () => {
      frame = 0
      let current: string | null = null
      for (const title of titles) {
        const element = document.getElementById(sectionId(title))
        if (element && element.getBoundingClientRect().top <= 144) current = element.id
      }
      setActive(current)
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update)
    }
    update()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
    }
  }, [titles])
  return (
    <nav
      aria-label="Investigation sections"
      className="sticky top-0 z-20 -mx-4 flex overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden border-b border-border bg-background px-4 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8"
    >
      {titles.map((title) => {
        const id = sectionId(title)
        return (
          <a
            key={title}
            href={`#${id}`}
            aria-current={active === id ? 'location' : undefined}
            className={cn(
              'inline-flex min-h-11 shrink-0 items-center border-b-2 px-3 text-sm font-semibold whitespace-nowrap',
              active === id
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {title}
          </a>
        )
      })}
    </nav>
  )
}
