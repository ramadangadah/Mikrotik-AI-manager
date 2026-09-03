import React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./context/AuthContext.jsx";
import Layout from "./components/Layout.jsx";

import LoginPage from "./pages/LoginPage.jsx";
import ChangePasswordPage from "./pages/ChangePasswordPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import RoutersPage from "./pages/RoutersPage.jsx";
import RouterDetailPage from "./pages/RouterDetailPage.jsx";
import CpesPage from "./pages/CpesPage.jsx";
import CpeDetailPage from "./pages/CpeDetailPage.jsx";
import AlertsPage from "./pages/AlertsPage.jsx";
import FirmwarePage from "./pages/FirmwarePage.jsx";
import PppoePage from "./pages/PppoePage.jsx";
import BackupsPage from "./pages/BackupsPage.jsx";
import UsersPage from "./pages/UsersPage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";
import AssistantPage from "./pages/AssistantPage.jsx";

function RequireAuth({ children }) {
  const { token, mustChangePassword } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  if (mustChangePassword) return <Navigate to="/change-password" replace />;
  return children;
}

function RequireAdmin({ children }) {
  const { role } = useAuth();
  if (role !== "admin") return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/change-password" element={<ChangePasswordPage />} />

      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/routers" element={<RoutersPage />} />
        <Route path="/routers/:id" element={<RouterDetailPage />} />
        <Route path="/cpes" element={<CpesPage />} />
        <Route path="/cpes/:id" element={<CpeDetailPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/firmware" element={<FirmwarePage />} />
        <Route path="/pppoe" element={<PppoePage />} />
        <Route path="/backups" element={<BackupsPage />} />
        <Route path="/assistant" element={<AssistantPage />} />
        <Route
          path="/users"
          element={
            <RequireAdmin>
              <UsersPage />
            </RequireAdmin>
          }
        />
        <Route
          path="/settings"
          element={
            <RequireAdmin>
              <SettingsPage />
            </RequireAdmin>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
