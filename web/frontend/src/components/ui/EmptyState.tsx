import { Inbox } from 'lucide-react';

interface EmptyStateProps {
  message?: string;
}

export function EmptyState({ message = '데이터가 없습니다' }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-slate-500">
      <Inbox className="w-12 h-12 mb-3" />
      <p className="text-sm">{message}</p>
    </div>
  );
}
