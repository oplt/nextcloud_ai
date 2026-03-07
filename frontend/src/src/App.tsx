import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Home from "./pages/Home";
import SignIn from "./pages/SignIn";
import SignUp from "./pages/SignUp";
import Dashboard from "./pages/dashboard/Dashboard";
import { ProtectedRoute } from "./ProtectedRoute";
import { getToken } from "./auth";

import DashboardHome from "./pages/dashboard/tabs/HomePage";
import TasksPage from "./pages/dashboard/tabs/TasksPage";
import SettingsPage from "./pages/dashboard/tabs/SettingsPage";
import AccountPage from "./pages/dashboard/tabs/AccountPage";
import ProfilePage from "./pages/dashboard/tabs/ProfilePage";
import InsightsPage from "./pages/dashboard/tabs/InsightsPage";
import FleetPage from "./pages/dashboard/tabs/FleetPage";
import TerrainPage from "./pages/dashboard/tabs/TerrainPage";
import PhotoGrammetryPage from "./pages/dashboard/tabs/PhotoGrammetry";
import FieldPage from "./pages/dashboard/tabs/FieldPage";
import AnimalFarmPage from "./pages/dashboard/tabs/AnimalFarmPage";
import PrivatePatrolPage from "./pages/dashboard/tabs/PrivatePatrolPage";
import "cesium/Build/Cesium/Widgets/widgets.css";

function RedirectIfAuthenticated({ children }: { children: React.ReactNode }) {
  const token = getToken();
  if (token) {
    return <Navigate to="/dashboard" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter
      future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
    >
      <Routes>
        <Route path="/" element={
          <RedirectIfAuthenticated>
            <Home />
          </RedirectIfAuthenticated>
        } />
        <Route path="/signin" element={
          <RedirectIfAuthenticated>
            <SignIn />
          </RedirectIfAuthenticated>
        } />
        <Route path="/signup" element={
          <RedirectIfAuthenticated>
            <SignUp />
          </RedirectIfAuthenticated>
        } />
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        >
          <Route index element={<DashboardHome />} />
          <Route path="tasks" element={<TasksPage />} />
          <Route path="insights" element={<InsightsPage />} />
          <Route path="fleet" element={<FleetPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="terrain" element={<TerrainPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="account" element={<AccountPage />} />
          <Route path="photogrammetry" element={<PhotoGrammetryPage />} />
          <Route path="animalfarm" element={<AnimalFarmPage />} />
          <Route path="privatepatrol" element={<PrivatePatrolPage />} />
          <Route path="field" element={<FieldPage />} />

        </Route>
      </Routes>
    </BrowserRouter>
  );
}
