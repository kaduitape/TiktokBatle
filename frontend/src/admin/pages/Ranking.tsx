import { useEffect, useState } from "react";
import { api } from "../../api/client";

interface Battle {
  id: string;
  name: string;
}

interface RankingEntry {
  username: string;
  nickname: string | null;
  team: string;
  damage_total: number;
  heal_total: number;
  gifts_total: number;
  combo_count: number;
  score: number;
}

export default function Ranking() {
  const [battles, setBattles] = useState<Battle[]>([]);
  const [battleId, setBattleId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [entries, setEntries] = useState<RankingEntry[]>([]);

  useEffect(() => {
    api.get<Battle[]>("/api/battles").then((bs) => {
      setBattles(bs);
      if (bs[0]) setBattleId(bs[0].id);
    });
  }, []);

  useEffect(() => {
    if (!battleId) return;
    api.get<{ id: string }>(`/api/battles/${battleId}/session`).then((s) => setSessionId(s.id)).catch(() => setSessionId(""));
  }, [battleId]);

  const refresh = () => {
    if (sessionId) api.get<RankingEntry[]>(`/api/sessions/${sessionId}/ranking?limit=20`).then(setEntries);
  };

  useEffect(refresh, [sessionId]);

  return (
    <div>
      <h1>Ranking</h1>
      <div className="card">
        <label>Batalha</label>
        <select value={battleId} onChange={(e) => setBattleId(e.target.value)}>
          {battles.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="secondary" onClick={refresh}>Atualizar</button>
        </div>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>#</th><th>Jogador</th><th>Time</th><th>Dano</th><th>Cura</th><th>Presentes</th><th>Combo</th><th>Score</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={e.username}>
                <td>{i + 1}</td>
                <td>{e.nickname || e.username}</td>
                <td>{e.team}</td>
                <td>{Math.round(e.damage_total)}</td>
                <td>{Math.round(e.heal_total)}</td>
                <td>{e.gifts_total}</td>
                <td>{e.combo_count}</td>
                <td>{Math.round(e.score)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
