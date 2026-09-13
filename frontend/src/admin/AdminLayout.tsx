import { Navigate, NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken, isAuthenticated } from "../auth";

const links = [
  { to: "/admin", label: "Dashboard", end: true },
  { to: "/admin/live", label: "Ao vivo" },
  { to: "/admin/battles", label: "Batalhas" },
  { to: "/admin/characters", label: "Personagens" },
  { to: "/admin/gifts", label: "Presentes" },
  { to: "/admin/sprites", label: "Gerar sprites" },
  { to: "/admin/editor", label: "Editor de Arena" },
  { to: "/admin/music", label: "Músicas" },
  { to: "/admin/simulator", label: "Simulador" },
  { to: "/admin/ranking", label: "Ranking" },
];

export default function AdminLayout() {
  const navigate = useNavigate();

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
