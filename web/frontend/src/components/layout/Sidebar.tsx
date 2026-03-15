import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Briefcase,
  Eye,
  Bell,
  LogOut,
  ArrowLeftRight,
  TrendingUp,
  BookOpen,
  FileText,
  ScrollText,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { clsx } from 'clsx';
import { MarketSelector } from '@/components/ui/MarketSelector';

interface NavItem {
  to: string;
  icon: LucideIcon;
  label: string;
  end?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', icon: LayoutDashboard, label: '대시보드', end: true },
  { to: '/positions', icon: Briefcase, label: '포지션' },
  { to: '/watchlist', icon: Eye, label: '관심종목' },
  { to: '/alerts', icon: Bell, label: '진입알림' },
  { to: '/exit-alerts', icon: LogOut, label: '청산알림' },
  { to: '/trades', icon: ArrowLeftRight, label: '매매내역' },
  { to: '/pnl', icon: TrendingUp, label: '손익분석' },
  { to: '/ibd', icon: TrendingUp, label: 'IBD 시장방향' },
  { to: '/journal', icon: BookOpen, label: '매매일지' },
  { to: '/diary', icon: FileText, label: '종목일기' },
  { to: '/logs', icon: ScrollText, label: '봇 로그' },
];

export function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 h-screen w-56 bg-panel border-r border-slate-700/50 flex flex-col">
      <div className="px-5 py-6">
        <h1 className="text-xl font-bold">
          <span className="text-blue-400">SN</span>
          <span className="text-slate-100">OWA</span>
        </h1>
      </div>

      <MarketSelector />

      <nav className="flex-1 px-3 space-y-1">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                isActive
                  ? 'bg-slate-700/50 text-blue-400'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50',
              )
            }
          >
            <item.icon className="w-4 h-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
