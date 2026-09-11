import { Navigate, Route, HashRouter as Router, Routes } from "react-router-dom";
import AdminLayout from "./admin/AdminLayout";
import Battles from "./admin/pages/Battles";
import Characters from "./admin/pages/Characters";
import Dashboard from "./admin/pages/Dashboard";
import Editor from "./admin/pages/Editor";
import Gifts from "./admin/pages/Gifts";
import Live from "./admin/pages/Live";
import Login from "./admin/pages/Login";
import Music from "./admin/pages/Music";
import Ranking from "./admin/pages/Ranking";
import Simulator from "./admin/pages/Simulator";
import ArenaPage from "./arena/ArenaPage";

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Navigate to="/admin" replace />} />
        <Route path="/arena" element={<ArenaPage />} />
        <Route path="/admin/login" element={<Login />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="live" element={<Live />} />
          <Route path="battles" element={<Battles />} />
          <Route path="characters" element={<Characters />} />
          <Route path="gifts" element={<Gifts />} />
          <Route path="editor" element={<Editor />} />
          <Route path="music" element={<Music />} />
          <Route path="simulator" element={<Simulator />} />
          <Route path="ranking" element={<Ranking />} />
        </Route>
      </Routes>
    </Router>
  );
}
