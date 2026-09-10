import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";

export default function Dashboard() {
  const [health, setHealth] = useState<"checking" | "ok" | "down">("checking");
  const [counts, setCounts] = useState({ battles: 0, characters: 0, gifts: 0 });

  useEffect(() => {
    api
      .get("/api/health")
      .then(() => setHealth("ok"))
      .catch(() => setHealth("down"));

    Promise.all([
      api.get<any[]>("/api/battles").catch(() => []),
      api.get<any[]>("/api/characters").catch(() => []),
      api.get<any[]>("/api/gifts").catch(() => []),
    ]).then(([battles, characters, gifts]) =>
      setCounts({ battles: battles.length, characters: characters.length, gifts: gifts.length })
    );
  }, []);

  return (
    <div>
      <h1>Dashboard</h1>
      <div className="card">
        <div className="row">
          <span className="pill">Backend: {health === "checking" ? "verificando…" : health === "ok" ? "🟢 online" : "🔴 offline"}</span>
        </div>
      </div>

      <div className="card">
        <h3>Resumo</h3>
        <div className="row">
          <span className="pill">{counts.battles} batalhas</span>
          <span className="pill">{counts.characters} personagens</span>
          <span className="pill">{counts.gifts} presentes</span>
        </div>
      </div>

      <div className="card">
        <h3>Fluxo principal (núcleo do produto)</h3>
        <p style={{ fontSize: 13, color: "#b6b6d0" }}>
          Espectador → Presente → Identificar usuário → Obter avatar → Localizar/criar bolinha →
          Bolinha executa ação → Projétil atinge personagem → XP alterado → Efeito visual → Ranking atualizado.
        </p>
        <div className="row">
          <Link to="/admin/simulator"><button>Ir para o Simulador</button></Link>
          <a href="#/arena" target="_blank" rel="noreferrer"><button className="secondary">Abrir Arena</button></a>
        </div>
      </div>
    </div>
  );
}
