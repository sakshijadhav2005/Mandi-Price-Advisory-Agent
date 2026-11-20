import type { ConversationSummary } from "@mandi/shared";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useApp } from "../lib/app-context";

export function HistoryPage() {
  const { t } = useTranslation();
  const { api } = useApp();
  const [items, setItems] = useState<ConversationSummary[] | null>(null);

  useEffect(() => {
    api
      .conversations()
      .then(setItems)
      .catch(() => setItems([]));
  }, [api]);

  const remove = async (id: number) => {
    await api.deleteConversation(id);
    setItems((xs) => xs?.filter((x) => x.id !== id) ?? null);
  };

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">{t("history.title")}</h2>
      {items?.length === 0 && <p className="text-muted">{t("history.empty")}</p>}
      <ul className="space-y-2">
        {items?.map((c) => (
          <li key={c.id} className="card flex items-center gap-3">
            <Link to={`/c/${c.id}`} className="min-w-0 flex-1" lang={c.language}>
              <p className="truncate font-medium">{c.title}</p>
              <p className="text-sm text-muted">
                {new Date(c.created_at).toLocaleDateString()} · {t("history.messages", { count: c.messages })}
              </p>
            </Link>
            <button type="button" className="btn-ghost min-h-[40px] px-3 text-sm" onClick={() => void remove(c.id)}>
              {t("history.delete")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
