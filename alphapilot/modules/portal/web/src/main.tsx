import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { ConfirmProvider, Layout } from "./components";
import { I18nProvider } from "./i18n";
import { ToastProvider } from "./toast";
import {
  AdvancedPage,
  BacktestPage,
  DailyTradePage,
  HomePage,
  LibraryPage,
  MarketPage,
  MiningPage,
  NotificationsPage,
  SchedulerPage
} from "./pages";
import "./styles.css";

// Apply the saved theme before first paint to avoid a flash of the wrong theme.
document.documentElement.dataset.theme = localStorage.getItem("portal_theme") === "dark" ? "dark" : "light";

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "mining", element: <MiningPage /> },
      { path: "backtest", element: <BacktestPage /> },
      { path: "library", element: <LibraryPage /> },
      { path: "market", element: <MarketPage /> },
      { path: "daily-trade", element: <DailyTradePage /> },
      { path: "scheduler", element: <SchedulerPage /> },
      { path: "notifications", element: <NotificationsPage /> },
      { path: "advanced", element: <AdvancedPage /> }
    ]
  }
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <I18nProvider>
      <ToastProvider>
        <ConfirmProvider>
          <RouterProvider router={router} />
        </ConfirmProvider>
      </ToastProvider>
    </I18nProvider>
  </React.StrictMode>
);
