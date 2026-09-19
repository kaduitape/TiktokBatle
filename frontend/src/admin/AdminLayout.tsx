import { useEffect, useState } from "react";
import { Navigate, NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { clearToken, isAuthenticated } from "../auth";

const links = [
  { to: "/admin", label: "Dashboard", end: true },
  { to: "/admin/live", label: "Ao vivo" },
  { to: "/admin/battles", label: "Batalhas" },
  { to: "/admin/characters", label: "Personagens" },
  { to: "/admin/gifts", label: "Presentes" },
  { to: "/admin/live-gifts", label: "Presentes da LIVE", badge: "unconfigured" },
  { to: "/admin/sprites", label: "Gerar sprites" },
  { to: "/admin/editor", label: "Editor de Arena" },
  { to: "/admin/music", label: "Músicas" },
  { to: "/admin/simulator", label: "Simulador" },
  { to: "/admin/ranking", label: "Ranking" },
];

export default function AdminLayout() {
  const navigate = useNavigate();
  // Section 13: how many captured gifts still have no action. Polled rather
  // than pushed because the badge is shown on every page, not just the
  // catalogue, and a socket per page would be a lot of sockets.
  const [unconfigured, setUnconfigured] = useState(0);

  useEffect(() => {
    if (!isAuthenticated()) return;
    let cancelled = false;
    const check = () =>
      api
        .get<{ unconfigured: number }>("/api/live-gifts/summary")
        .then((s) => !cancelled && setUnconfigured(s.unconfigured))
        .catch(() => undefined);
    void check();
    const timer = window.setInterval(check, 20000);
    // The catalogue page knows about a new gift long before the next poll --
    // without this the badge sits there contradicting the page it links to.
    window.addEventListener("gift-catalog-changed", check);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener("gift-catalog-changed", check);
    };
  }, []);

  if (!isAuthenticated()) {
    return <Navigate to="/admin/login" replace />;
  }

  const logout = () => {
    clearToken();
    navigate("/admin/login", { replace: true });
  };

  return (
    <div className="admin-layout">
      <nav className="admin-nav">
        <div className="brand">⚔️ Battle Arena</div>
        {links.map((l) => (
          <NavLink key={l.to} to={l.to} end={l.end}>
            {l.label}
            {l.badge === "unconfigured" && unconfigured > 0 && (
              <span className="nav-badge">
                {unconfigured} novo{unconfigured === 1 ? "" : "s"}
              </span>
            )}
          </NavLink>
        ))}
        <a href="#/arena" target="_blank" rel="noreferrer">
          🎮 Abrir Arena (fonte OBS)
        </a>
        <a href="#" onClick={(e) => { e.preventDefault(); logout(); }}>
          🚪 Sair
        </a>
      </nav>
      <div className="admin-content">
        <Outlet />
      </div>
    </div>
  );
}
