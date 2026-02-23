import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { SWRConfig } from 'swr';
import { DashboardLayout } from '@/components/layout/DashboardLayout';
import { OverviewPage } from '@/pages/OverviewPage';
import { PositionsPage } from '@/pages/PositionsPage';
import { WatchlistPage } from '@/pages/WatchlistPage';
import { TradesPage } from '@/pages/TradesPage';
import { PnlPage } from '@/pages/PnlPage';
import { JournalPage } from '@/pages/JournalPage';
import { DiaryPage } from '@/pages/DiaryPage';
import { LogsPage } from '@/pages/LogsPage';
import { AlertsPage } from '@/pages/AlertsPage';
import { ExitAlertsPage } from '@/pages/ExitAlertsPage';
import { fetcher } from '@/lib/fetcher';

const router = createBrowserRouter([
  {
    element: <DashboardLayout />,
    children: [
      { path: '/', element: <OverviewPage /> },
      { path: '/positions', element: <PositionsPage /> },
      { path: '/watchlist', element: <WatchlistPage /> },
      { path: '/alerts', element: <AlertsPage /> },
      { path: '/exit-alerts', element: <ExitAlertsPage /> },
      { path: '/trades', element: <TradesPage /> },
      { path: '/pnl', element: <PnlPage /> },
      { path: '/journal', element: <JournalPage /> },
      { path: '/diary', element: <DiaryPage /> },
      { path: '/logs', element: <LogsPage /> },
    ],
  },
]);

export default function App() {
  return (
    <SWRConfig value={{ fetcher, revalidateOnFocus: false, errorRetryCount: 3, dedupingInterval: 5000 }}>
      <RouterProvider router={router} />
    </SWRConfig>
  );
}
