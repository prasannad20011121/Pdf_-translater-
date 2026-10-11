import { FlaskConical } from "lucide-react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { SettingsProvider, useSettings } from "./lib/settings-context";
import GlossaryPage from "./pages/GlossaryPage";
import JobPage from "./pages/JobPage";
import JobsPage from "./pages/JobsPage";
import SettingsPage from "./pages/SettingsPage";
import UploadPage from "./pages/UploadPage";

function DevBanner() {
  const { settings, error } = useSettings();
  if (error) {
    return (
      <div className="border-t border-border bg-bad-soft px-4 py-2 text-center text-sm text-bad">
        Can't reach the translator service: {error}
      </div>
    );
  }
  if (!settings?.dev_mode) return null;
  return (
    <div className="flex items-center justify-center gap-2 border-t border-border bg-warn-soft px-4 py-2 text-center text-sm text-warn">
      <FlaskConical className="h-4 w-4 shrink-0" aria-hidden />
      Developer mode: a stand-in engine transliterates the Hindi. This is not a real translation.
    </div>
  );
}

export default function App() {
  return (
    <SettingsProvider>
      <Layout banner={<DevBanner />}>
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:id" element={<JobPage />} />
          <Route path="/glossary" element={<GlossaryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<UploadPage />} />
        </Routes>
      </Layout>
    </SettingsProvider>
  );
}
