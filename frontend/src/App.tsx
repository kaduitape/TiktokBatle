import { Navigate, Route, HashRouter as Router, Routes } from "react-router-dom";
import AdminLayout from "./admin/AdminLayout";
import Battles from "./admin/pages/Battles";
import Characters from "./admin/pages/Characters";
import Dashboard from "./admin/pages/Dashboard";
import Gifts from "./admin/pages/Gifts";
import Ranking from "./admin/pages/Ranking";
import Simulator from "./admin/pages/Simulator";
import ArenaPage from "./arena/ArenaPage";

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Navigate to="/admin" replace />} />
        <Route path="/arena" element={<ArenaPage />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="battles" element={<Battles />} />
          <Route path="characters" element={<Characters />} />
          <Route path="gifts" element={<Gifts />} />
          <Route path="simulator" element={<Simulator />} />
          <Route path="ranking" element={<Ranking />} />
        </Route>
      </Routes>
    </Router>
  );
}
