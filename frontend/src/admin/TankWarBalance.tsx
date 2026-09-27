import { useEffect, useState } from "react";
import { api } from "../api/client";

interface Balance {
  boss_damage_percent_per_coin: number;
  boss_max_hit_percent: number;
  boss_resistance_per_fighter: number;
  soldier_hp: number;
  bomb_interval_seconds: number;
  bomb_damage: number;
  [key: string]: unknown;
}

interface Props {
  /** Health of the boss being attacked, only for the worked examples. */
  bossHp?: number;
}

const pct = (value: number) => `${value.toLocaleString("pt-BR", { maximumFractionDigits: 3 })}%`;

/** How hard the viewers hit the bosses in Guerra de Tanques.
 *
 * Damage is a share of the boss's own health, so the same numbers give the
 * same length of battle whatever "vida máxima" the characters have. The
 * examples below are worked out from the fields as they are typed, so the
 * admin sees what a rose or a meteor will do before saving.
 */
export default function TankWarBalance({ bossHp = 100000 }: Props) {
  const [config, setConfig] = useState<Balance | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Balance>("/api/settings/tank_war").then(setConfig).catch((err) => setError(String(err)));
  }, []);

  if (!config) return error ? <p style={{ color: "#ff9b9b" }}>{error}</p> : null;

  const set = (key: keyof Balance, value: number) => {
    setMessage("");
    setConfig({ ...config, [key]: value });
  };

  const save = async () => {
    setError("");
    try {
      await api.put("/api/settings/tank_war", config);
      setMessage("Equilíbrio salvo. Vale a partir do próximo presente, sem reiniciar a batalha.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const perCoin = Number(config.boss_damage_percent_per_coin) || 0;
  const cap = Number(config.boss_max_hit_percent) || 0;
  const resistance = Number(config.boss_resistance_per_fighter) || 0;
  const hit = (coins: number, fighters: number) => {
    let share = coins * perCoin;
    if (cap > 0) share = Math.min(share, cap);
    return share / (1 + (resistance / 100) * fighters);
  };
  const coinsToKill = perCoin > 0 ? Math.ceil(100 / perCoin) : Infinity;

  const field = (label: string, key: keyof Balance, help: string, step = 1) => (
    <div>
      <label>{label}</label>
      <input
        type="number"
        min={0}
        step={step}
        value={Number(config[key])}
        onChange={(e) => set(key, Number(e.target.value))}
      />
      <p style={{ color: "#6a6a8a", fontSize: 12, margin: "2px 0 0" }}>{help}</p>
    </div>
  );

  return (
    <div className="card">
      <h3>Equilíbrio da Guerra de Tanques</h3>
      <p style={{ color: "#9a9ac0", fontSize: 13, marginTop: 0 }}>
        O dano é uma porcentagem da vida do chefão, então a batalha dura o mesmo com qualquer "vida máxima".
        Quanto mais gente entra, mais resistente o chefão fica.
      </p>
      <div className="form-grid">
        {field("Dano por moeda (% da vida)", "boss_damage_percent_per_coin", `O chefão cai com ${Number.isFinite(coinsToKill) ? coinsToKill.toLocaleString("pt-BR") : "∞"} moedas (sem resistência).`, 0.001)}
        {field("Dano máximo de um presente (% da vida)", "boss_max_hit_percent", "Nenhum presente sozinho tira mais que isto. 0 = sem limite.", 0.1)}
        {field("Resistência por soldado (%)", "boss_resistance_per_fighter", "Cada soldado atacando deixa o chefão esta porcentagem mais resistente.", 0.5)}
        {field("Vida do soldado", "soldier_hp", "Vida de cada espectador que entra em campo.")}
        {field("Bomba do chefão a cada (s)", "bomb_interval_seconds", "Intervalo entre as bombas de cada chefão.")}
        {field("Dano da bomba", "bomb_damage", "Igual ou maior que a vida do soldado elimina com uma bomba.")}
      </div>

      <table style={{ marginTop: 12 }}>
        <thead>
          <tr>
            <th>Presente</th>
            <th>1 soldado atacando</th>
            <th>20 soldados</th>
            <th>100 soldados</th>
          </tr>
        </thead>
        <tbody>
          {[
            ["🌹 1 moeda", 1],
            ["30 moedas", 30],
            ["100 moedas", 100],
            ["☄️ 500 moedas", 500],
          ].map(([label, coins]) => (
            <tr key={String(label)}>
              <td>{label}</td>
              {[1, 20, 100].map((fighters) => {
                const share = hit(Number(coins), fighters);
                return (
                  <td key={fighters}>
                    {pct(share)} <span style={{ color: "#6a6a8a" }}>({Math.round((share / 100) * bossHp).toLocaleString("pt-BR")})</span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ color: "#6a6a8a", fontSize: 12 }}>
        Entre parênteses: quanto sai de um chefão com {bossHp.toLocaleString("pt-BR")} de vida.
      </p>

      <div className="row" style={{ alignItems: "center", gap: 10 }}>
        <button onClick={save}>Salvar equilíbrio</button>
        {message && <span style={{ color: "#86efac", fontSize: 13 }}>{message}</span>}
        {error && <span style={{ color: "#ff9b9b", fontSize: 13 }}>{error}</span>}
      </div>
    </div>
  );
}
