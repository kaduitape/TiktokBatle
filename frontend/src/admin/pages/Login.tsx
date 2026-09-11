import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { API_BASE } from "../../api/client";
import { setToken } from "../../auth";

export default function Login() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) throw new Error("Usuário ou senha inválidos");
      const { token } = await res.json();
      setToken(token);
      navigate("/admin", { replace: true });
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <form onSubmit={submit} className="card" style={{ width: 320 }}>
        <h1 style={{ fontSize: 20, marginTop: 0 }}>⚔️ Battle Arena</h1>
        <p style={{ color: "#9a9ac0", fontSize: 13, marginTop: -6 }}>Painel administrativo</p>

        <label>Usuário</label>
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />

        <label>Senha</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />

        {error && <p style={{ color: "#ff8080", fontSize: 13, marginTop: 12 }}>{error}</p>}

        <div className="row" style={{ marginTop: 16 }}>
          <button type="submit" disabled={busy || !password}>
            {busy ? "Entrando…" : "Entrar"}
          </button>
        </div>
      </form>
    </div>
  );
}
