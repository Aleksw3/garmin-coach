import type { ReactNode } from 'react'

type Props = { title: string; subtitle?: string; children: ReactNode; className?: string }

export function Card({ title, subtitle, children, className = '' }: Props) {
  return (
    <section className={`min-w-0 rounded-xl border border-line bg-surface p-4 ${className}`}>
      <h2 className="text-sm font-semibold text-primary">{title}</h2>
      {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
      <div className="mt-3">{children}</div>
    </section>
  )
}

type TableProps = { columns: string[]; rows: (string | number)[][] }

export function DataTable({ columns, rows }: TableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="tabular w-full text-left text-xs">
        <thead>
          <tr className="text-muted">
            {columns.map((column) => (
              <th key={column} className="py-1 pr-3 font-medium whitespace-nowrap">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-t border-line text-secondary">
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="py-1 pr-3 whitespace-nowrap">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function TableToggle(props: TableProps) {
  return (
    <details className="mt-2 text-xs text-muted">
      <summary className="cursor-pointer select-none">Show table</summary>
      <div className="mt-2">
        <DataTable {...props} />
      </div>
    </details>
  )
}
