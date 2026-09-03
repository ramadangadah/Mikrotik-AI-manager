import axios from "axios";

const api = axios.create({ baseURL: "/api" });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Central place other modules can register a handler for "must change
// password" / "session expired" without importing the router here.
let onAuthProblem = null;
export function setAuthProblemHandler(fn) {
  onAuthProblem = fn;
}

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status;
    const detail = err.response?.data?.detail;
    if (status === 401 && onAuthProblem) onAuthProblem("unauthorized");
    if (status === 403 && detail === "Password change required before continuing." && onAuthProblem) {
      onAuthProblem("password_change_required");
    }
    return Promise.reject(err);
  }
);

export default api;
