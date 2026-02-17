import { Fragment, useState, useCallback } from 'react';
import type { ReactNode } from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';
import { clsx } from 'clsx';
import { EmptyState } from './EmptyState';

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  sortable?: boolean;
  className?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  onSort?: (key: string) => void;
  sortKey?: string;
  sortDir?: 'asc' | 'desc';
  rowKey: (row: T) => string | number;
  expandable?: boolean;
  renderExpanded?: (row: T) => ReactNode;
  emptyMessage?: string;
}

export function DataTable<T>({
  columns,
  data,
  onSort,
  sortKey,
  sortDir,
  rowKey,
  expandable,
  renderExpanded,
  emptyMessage,
}: DataTableProps<T>) {
  const [expanded, setExpanded] = useState<Map<string | number, boolean>>(
    new Map(),
  );

  const toggleExpanded = useCallback(
    (key: string | number) => {
      setExpanded((prev) => {
        const next = new Map(prev);
        next.set(key, !next.get(key));
        return next;
      });
    },
    [],
  );

  if (data.length === 0) {
    return <EmptyState message={emptyMessage} />;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="bg-slate-800/50">
            {columns.map((col) => (
              <th
                key={col.key}
                className={clsx(
                  'px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wide',
                  col.sortable && 'cursor-pointer select-none hover:text-slate-200',
                  col.className,
                )}
                onClick={col.sortable && onSort ? () => onSort(col.key) : undefined}
              >
                <span className="inline-flex items-center gap-1">
                  {col.header}
                  {col.sortable && sortKey === col.key && (
                    sortDir === 'asc' ? (
                      <ChevronUp className="w-3 h-3" />
                    ) : (
                      <ChevronDown className="w-3 h-3" />
                    )
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row) => {
            const key = rowKey(row);
            const isExpanded = expanded.get(key) ?? false;

            return (
              <Fragment key={key}>
                <tr
                  className={clsx(
                    'border-b border-slate-700/30 hover:bg-slate-800/30 transition-colors',
                    expandable && 'cursor-pointer',
                  )}
                  onClick={expandable ? () => toggleExpanded(key) : undefined}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={clsx('px-4 py-3 text-sm', col.className)}
                    >
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
                {expandable && isExpanded && renderExpanded && (
                  <tr>
                    <td
                      colSpan={columns.length}
                      className="px-4 py-3 bg-slate-800/20"
                    >
                      {renderExpanded(row)}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
