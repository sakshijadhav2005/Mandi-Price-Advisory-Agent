import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useApp } from "./lib/app-context";
import { AskPage } from "./pages/Ask";
import { HistoryPage } from "./pages/History";
import { LanguageScreen } from "./pages/LanguageScreen";
import { LoginPage } from "./pages/Login";
import { PricesPage } from "./pages/Prices";
import { SettingsPage } from "./pages/Settings";

export function App() {
  const { language, meta, loggedIn } = useApp();
  if (!language) return <LanguageScreen />;
  const mustLogin = meta?.auth_required && !loggedIn;
  return (
    <Layout>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        {mustLogin ? (
          <Route path="*" element={<Navigate to="/login" replace />} />
        ) : (
          <>
            <Route path="/" element={<AskPage />} />
            <Route path="/c/:id" element={<AskPageKeyed />} />
            <Route path="/prices" element={<PricesPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </>
        )}
      </Routes>
    </Layout>
  );
}

/** Remount the Ask page when switching between conversations. */
function AskPageKeyed() {
  const { pathname } = useLocation();
  return <AskPage key={pathname} />;
}
