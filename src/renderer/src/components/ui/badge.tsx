import * as React from 'react'
import { cn } from '@renderer/lib/utils'

function Badge({ className, ...props }: React.ComponentProps<'span'>): React.JSX.Element {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground',
        className
      )}
      {...props}
    />
  )
}

export { Badge }
