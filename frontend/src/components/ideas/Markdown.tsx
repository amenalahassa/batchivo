/**
 * Markdown of ideas and notes (spec 007).
 *
 * Raw HTML is never rendered (no `rehype-raw`), so a pasted `<script>` shows
 * as text; links open in a new tab without access to this page.
 */
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/lib/utils'

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn('prose prose-sm max-w-none dark:prose-invert break-words', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children: label }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {label}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
