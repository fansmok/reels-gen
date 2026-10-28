import * as LabelPrimitive from '@radix-ui/react-label'
import * as React from 'react'
import { cn } from '@renderer/lib/utils'

function Label({ className, ...props }: React.ComponentProps<typeof LabelPrimitive.Root>): React.JSX.Element {
  return <LabelPrimitive.Root className={cn('text-sm font-medium leading-none', className)} {...props} />
}

export { Label }
