import React from "react";
import { Navigate } from "react-router-dom";
import { getToken } from "./auth";

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = getToken();
  if (!token) return <Navigate to="/signin" replace />;
  return <>{children}</>;
}
