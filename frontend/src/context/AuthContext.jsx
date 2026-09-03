import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import api, { setAuthProblemHandler } from "../api/client.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem("token"));
  const [username, setUsername] = useState(() => localStorage.getItem("username"));
  const [role, setRole] = useState(() => localStorage.getItem("role"));
  const [mustChangePassword, setMustChangePassword] = useState(
    () => localStorage.getItem("mustChangePassword") === "true"
  );
  const [ready, setReady] = useState(false);

  const login = useCallback(async (u, p) => {
    const res = await api.post("/auth/login", { username: u, password: p });
    const { access_token, username: un, role: r, must_change_password } = res.data;
    localStorage.setItem("token", access_token);
    localStorage.setItem("username", un);
    localStorage.setItem("role", r);
    localStorage.setItem("mustChangePassword", String(must_change_password));
    setToken(access_token);
    setUsername(un);
    setRole(r);
    setMustChangePassword(must_change_password);
    return res.data;
  }, []);

  const logout = useCallback(() => {
    localStorage.clear();
    setToken(null);
    setUsername(null);
    setRole(null);
    setMustChangePassword(false);
  }, []);

  const completePasswordChange = useCallback(() => {
    localStorage.setItem("mustChangePassword", "false");
    setMustChangePassword(false);
  }, []);

  useEffect(() => {
    setAuthProblemHandler((kind) => {
      if (kind === "unauthorized") logout();
      if (kind === "password_change_required") {
        localStorage.setItem("mustChangePassword", "true");
        setMustChangePassword(true);
      }
    });
    setReady(true);
  }, [logout]);

  return (
    <AuthContext.Provider
      value={{ token, username, role, mustChangePassword, login, logout, completePasswordChange, ready }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
